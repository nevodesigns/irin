"""Task corpora: verification, scoring, and the rules that keep both honest.

The failure this file mostly guards against is silent and total: a task run that
scores the reference implementations instead of an agent's work. Every task
passes, the corpus reports a perfect result, and the number means nothing. The
separation that prevents it is enforced at the type level and tested here.
"""

import tempfile
import unittest
from pathlib import Path

from irinspec import HoleCount, Size, Spec, ValidSolid
from irineval import FailureCode, RecordedRunner, responses_from_pairs
from irinbench import KIND_REGRESSION, KIND_TASK, Corpus, CorpusError
from irinbench.run import resolve_artifact, run_task_corpus
from irinbench.verify import format_verification, verify_corpus

PLATE = "plate.step.py"


def facts(size, parts=1, faces=6, edges=12):
    return {
        "ok": True,
        "tokens": [
            {
                "summary": {
                    "leafOccurrenceCount": parts,
                    "faceCount": faces,
                    "edgeCount": edges,
                    "bounds": {"min": [0.0, 0.0, 0.0], "max": list(size)},
                },
                "entryFacts": {"size": list(size)},
            }
        ],
        "errors": [],
    }


VALIDATE_OK = {"ok": True, "occurrenceCount": 1, "failureCount": 0, "parts": [], "errors": []}


def a_task(spec_id="plate", z=8.0) -> Spec:
    return Spec(
        id=spec_id,
        prompt="A plate 100 by 70 from 8 mm stock.",
        assertions=(ValidSolid(), Size(z=z)),
    )


class SeparationTests(unittest.TestCase):
    """entries and references must never be the same thing."""

    def test_a_task_corpus_cannot_bind_artifacts_in_entries(self):
        with self.assertRaises(CorpusError) as ctx:
            Corpus(
                name="t", kind=KIND_TASK, root=Path("."),
                entries={"plate": "models/plate.step.py"}, specs=(a_task(),),
            )
        self.assertIn("score the same file", str(ctx.exception))

    def test_a_regression_corpus_cannot_carry_references(self):
        # Its specs were measured from the models in entries, so a reference
        # would be the same file under a second name.
        with self.assertRaises(CorpusError) as ctx:
            Corpus(
                name="r", kind=KIND_REGRESSION, root=Path("."),
                entries={"plate": "m.step.py"}, references={"plate": "m.step.py"},
                specs=(a_task(),),
            )
        self.assertIn("no references", str(ctx.exception))

    def test_a_task_may_be_authored_before_anything_implements_it(self):
        corpus = Corpus(name="t", kind=KIND_TASK, root=Path("."), specs=(a_task(),))
        self.assertEqual(corpus.unreferenced(), ("plate",))

    def test_references_survive_a_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tasks"
            Corpus(
                name="tasks", kind=KIND_TASK, root=root,
                references={"plate": "models/plate.step.py"}, specs=(a_task(),),
            ).save()
            loaded = Corpus.load(root)
            self.assertEqual(loaded.references, {"plate": "models/plate.step.py"})
            self.assertEqual(loaded.entries, {})
            self.assertEqual(loaded.unreferenced(), ())


class VerificationTests(unittest.TestCase):
    def _corpus(self, spec):
        return Corpus(
            name="tasks", kind=KIND_TASK, root=Path("."),
            references={spec.id: PLATE}, specs=(spec,),
        )

    def _runner(self, size=(100.0, 70.0, 8.0)):
        return RecordedRunner(
            responses_from_pairs(
                {("refs", PLATE, "--facts"): facts(size), ("validate", PLATE): VALIDATE_OK}.items()
            )
        )

    def test_a_satisfiable_task_verifies(self):
        result = verify_corpus(self._corpus(a_task()), self._runner())
        self.assertTrue(result.ok)
        self.assertEqual(len(result.satisfiable), 1)

    def test_a_task_its_own_reference_fails_is_reported_as_broken(self):
        # The whole reason verification exists: an assertion authored from
        # intent can simply be wrong, and nothing else would catch it.
        result = verify_corpus(self._corpus(a_task(z=12.0)), self._runner())
        self.assertFalse(result.ok)
        self.assertEqual([r.spec_id for r in result.broken], ["plate"])
        self.assertIn("must be fixed before shipping", format_verification(result))

    def test_verification_refuses_a_regression_corpus(self):
        corpus = Corpus(
            name="r", kind=KIND_REGRESSION, root=Path("."),
            entries={"plate": PLATE}, specs=(a_task(),),
        )
        with self.assertRaises(CorpusError) as ctx:
            verify_corpus(corpus, self._runner())
        self.assertIn("pass by construction", str(ctx.exception))

    def test_an_unreferenced_task_is_reported_not_silently_skipped(self):
        corpus = Corpus(name="t", kind=KIND_TASK, root=Path("."), specs=(a_task(),))
        result = verify_corpus(corpus, self._runner())
        self.assertEqual(result.unreferenced, ("plate",))
        self.assertIn("nothing yet proves them buildable", format_verification(result))


class ArtifactResolutionTests(unittest.TestCase):
    def test_a_generator_is_preferred_over_an_exported_step(self):
        # The generator is what a repair loop would have to edit.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plate.step.py").write_text("", encoding="utf-8")
            (Path(tmp) / "plate.step").write_text("", encoding="utf-8")
            self.assertEqual(resolve_artifact(tmp, "plate"), "plate.step.py")

    def test_the_name_is_relative_not_absolute(self):
        # The CAD CLI refuses an absolute target outside its working directory,
        # so an absolute name would make every submission unreadable.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plate.stp").write_text("", encoding="utf-8")
            resolved = resolve_artifact(tmp, "plate")
            self.assertEqual(resolved, "plate.stp")
            self.assertFalse(Path(resolved).is_absolute())

    def test_nothing_produced_resolves_to_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_artifact(tmp, "plate"))


class TaskRunTests(unittest.TestCase):
    def _corpus(self, *specs):
        return Corpus(
            name="tasks", kind=KIND_TASK, root=Path("."),
            references={s.id: PLATE for s in specs}, specs=specs,
        )

    def test_a_task_that_produced_nothing_is_a_defect_not_undetermined(self):
        # An agent given a prompt and returning nothing has failed. Scoring that
        # as inconclusive would let the worst outcome report as the mildest.
        with tempfile.TemporaryDirectory() as tmp:
            runner = RecordedRunner({})
            run = run_task_corpus(self._corpus(a_task()), tmp, runner)
            self.assertEqual(run.missing_artifacts, 1)
            self.assertEqual(run.with_undetermined, 0)
            self.assertEqual(run.with_defects, 1)
            codes = {a.code for r in run.results for a in r.failures()}
            self.assertEqual(codes, {FailureCode.ARTIFACT_MISSING})

    def test_the_missing_artifact_message_names_where_it_looked(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = run_task_corpus(self._corpus(a_task()), tmp, RecordedRunner({}))
            detail = run.results[0].failures()[0].detail
            self.assertIn("plate.step.py", detail)

    def test_a_runner_rooted_elsewhere_is_refused(self):
        # Artifacts are named relative to their own directory, so a mismatched
        # runner would score every submission as undetermined.
        class Rooted:
            cwd = Path("/somewhere/else")

            def run(self, argv):  # pragma: no cover - never reached
                raise AssertionError("should not run")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError) as ctx:
                run_task_corpus(self._corpus(a_task()), tmp, Rooted())
            self.assertIn("submission directory", str(ctx.exception))

    def test_run_task_corpus_refuses_a_regression_corpus(self):
        corpus = Corpus(
            name="r", kind=KIND_REGRESSION, root=Path("."),
            entries={"plate": PLATE}, specs=(a_task(),),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError):
                run_task_corpus(corpus, tmp, RecordedRunner({}))

    def test_a_submitted_artifact_is_scored_on_its_own_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plate.step.py").write_text("", encoding="utf-8")
            runner = RecordedRunner(
                responses_from_pairs(
                    {
                        ("refs", "plate.step.py", "--facts"): facts((100.0, 70.0, 8.0)),
                        ("validate", "plate.step.py"): VALIDATE_OK,
                    }.items()
                )
            )
            run = run_task_corpus(self._corpus(a_task()), tmp, runner)
            self.assertEqual(run.passing, 1)
            self.assertEqual(run.missing_artifacts, 0)

    def test_a_wrong_submission_fails_on_the_assertion_it_misses(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "plate.step.py").write_text("", encoding="utf-8")
            runner = RecordedRunner(
                responses_from_pairs(
                    {
                        ("refs", "plate.step.py", "--facts"): facts((100.0, 70.0, 12.0)),
                        ("validate", "plate.step.py"): VALIDATE_OK,
                    }.items()
                )
            )
            run = run_task_corpus(self._corpus(a_task()), tmp, runner)
            self.assertEqual(run.passing, 0)
            self.assertEqual(run.missing_artifacts, 0)
            self.assertEqual(
                run.results[0].failures()[0].code, FailureCode.DIMENSION_OUT_OF_TOLERANCE
            )


class ShippedCorpusTests(unittest.TestCase):
    """The corpus this repository actually ships."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[4] / "benchmarks" / "tasks"

    def test_it_loads(self):
        corpus = Corpus.load(self.root)
        self.assertEqual(corpus.kind, KIND_TASK)
        self.assertGreaterEqual(len(corpus.specs), 15)

    def test_every_task_has_a_reference_proving_it_buildable(self):
        corpus = Corpus.load(self.root)
        self.assertEqual(
            corpus.unreferenced(),
            (),
            "an unreferenced task has nothing showing it can be satisfied",
        )

    def test_no_task_is_bound_to_an_artifact(self):
        self.assertEqual(Corpus.load(self.root).entries, {})

    def test_every_prompt_reads_as_a_requirement(self):
        # A task prompt is handed to an agent. One that describes a measurement
        # would be a derived spec wearing the wrong label.
        for spec in Corpus.load(self.root).specs:
            self.assertNotIn("Regression baseline", spec.prompt, spec.id)
            self.assertGreater(len(spec.prompt), 60, f"{spec.id} prompt is too thin")
            self.assertTrue(spec.assertions, spec.id)


if __name__ == "__main__":
    unittest.main()
