"""Repair sessions: recovery accounting, regressions, and what a brief may say.

Two properties matter more than the rest.

A brief must never contain anything from the reference implementation. Every
task has one, and leaking it would turn repair into transcription and the whole
metric into a measure of copying.

And a repair that fixes what was reported while breaking what was not is a real
outcome. A loop that counted only recoveries would score it as progress, so
regressions are tracked separately and asserted here.
"""

import tempfile
import unittest
from pathlib import Path

from irinspec import HoleCount, Size, Spec, ValidSolid
from irineval import AssertionResult, FailureCode, SpecResult
from irinbench import KIND_TASK, Corpus, CorpusError
from irinbench.repair import (
    RepairSession,
    format_session,
    new_session,
    repair_brief,
    write_briefs,
)
from irinbench.run import RunResult

REFERENCE = "models/step/parts/secret_reference.step.py"


def a_task(spec_id="plate") -> Spec:
    return Spec(
        id=spec_id,
        prompt="A plate 100 by 70 from 8 mm stock, with two 6 mm through-holes.",
        assertions=(ValidSolid(), Size(z=8.0), HoleCount(value=2, diameter=6.0)),
    )


def result_for(spec: Spec, *, passing: set[str], entry="plate.step.py") -> SpecResult:
    return SpecResult(
        spec_id=spec.id,
        entry=entry,
        results=tuple(
            AssertionResult(
                kind=a.kind,
                description=a.describe(),
                passed=a.kind in passing,
                code=None if a.kind in passing else FailureCode.COUNT_MISMATCH,
                detail="" if a.kind in passing else "expected 2, found 0",
            )
            for a in spec.assertions
        ),
    )


def a_round(*results: SpecResult) -> RunResult:
    return RunResult(corpus_name="tasks", corpus_kind=KIND_TASK, results=results)


def a_session(root, *rounds: RunResult) -> RepairSession:
    session = RepairSession(
        session_id="s1",
        corpus_name="tasks",
        corpus_root="benchmarks/tasks",
        artifacts_dir="/tmp/agent",
        root=Path(root),
    )
    session.rounds.extend(rounds)
    return session


ALL = {"valid_solid", "size", "hole_count"}
SOME = {"valid_solid", "size"}


class AccountingTests(unittest.TestCase):
    def test_first_pass_counts_only_round_zero(self):
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(tmp, a_round(result_for(spec, passing=ALL)))
            self.assertEqual(session.first_pass(), {"plate"})
            self.assertEqual(session.metrics()["rates"]["first_pass"], 1.0)

    def test_a_task_recovered_at_the_round_it_first_passed(self):
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(
                tmp,
                a_round(result_for(spec, passing=SOME)),
                a_round(result_for(spec, passing=ALL)),
            )
            self.assertEqual(session.recovered_at(), {1: {"plate"}})
            self.assertEqual(session.first_pass(), set())
            self.assertEqual(session.unrecovered(), set())

    def test_a_recovery_is_counted_once_not_every_round_after(self):
        # Otherwise the rounds would not sum to anything meaningful.
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(
                tmp,
                a_round(result_for(spec, passing=SOME)),
                a_round(result_for(spec, passing=ALL)),
                a_round(result_for(spec, passing=ALL)),
            )
            self.assertEqual(session.recovered_at(), {1: {"plate"}})
            self.assertEqual(session.metrics()["recovered_total"], 1)

    def test_a_repair_that_breaks_something_else_is_recorded_as_a_regression(self):
        # The outcome a recovery count alone would hide.
        one, two = a_task("one"), a_task("two")
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(
                tmp,
                a_round(result_for(one, passing=ALL), result_for(two, passing=SOME)),
                a_round(result_for(one, passing=SOME), result_for(two, passing=ALL)),
            )
            self.assertEqual(session.regressed(), {1: {"one"}})
            self.assertEqual(session.recovered_at(), {1: {"two"}})
            self.assertIn("regressions", format_session(session))

    def test_the_final_rate_reflects_the_last_round_not_the_best_one(self):
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(
                tmp,
                a_round(result_for(spec, passing=ALL)),
                a_round(result_for(spec, passing=SOME)),
            )
            self.assertEqual(session.unrecovered(), {"plate"})
            self.assertEqual(session.metrics()["rates"]["final"], 0.0)

    def test_an_id_that_is_not_a_slug_is_refused(self):
        with self.assertRaises(CorpusError):
            RepairSession(
                session_id="Not A Slug",
                corpus_name="tasks",
                corpus_root=".",
                artifacts_dir=".",
                root=Path("."),
            )


class BriefTests(unittest.TestCase):
    def test_a_brief_carries_the_requirement_and_the_measured_failure(self):
        spec = a_task()
        brief = repair_brief(spec, result_for(spec, passing=SOME), round_index=0)
        self.assertIn(spec.prompt, brief)
        self.assertIn("hole_count", brief)
        self.assertIn("expected 2, found 0", brief)

    def test_a_brief_lists_what_must_keep_passing(self):
        # Without this an agent can fix the reported failure and break the rest.
        spec = a_task()
        brief = repair_brief(spec, result_for(spec, passing=SOME), round_index=0)
        self.assertIn("What is already right", brief)
        self.assertIn("valid_solid", brief)

    def test_a_brief_never_names_the_reference_implementation(self):
        # Leaking it would turn repair into copying and the metric into nothing.
        spec = a_task()
        brief = repair_brief(spec, result_for(spec, passing=SOME), round_index=1)
        self.assertNotIn(REFERENCE, brief)
        self.assertNotIn("secret_reference", brief)
        self.assertNotIn("models/step/parts", brief)

    def test_a_missing_artifact_brief_says_produce_one(self):
        spec = a_task()
        result = SpecResult(
            spec_id=spec.id,
            entry="/tmp/agent/plate.step.py",
            results=tuple(
                AssertionResult(
                    kind=a.kind,
                    description=a.describe(),
                    passed=False,
                    code=FailureCode.ARTIFACT_MISSING,
                    detail="no artifact",
                )
                for a in spec.assertions
            ),
        )
        brief = repair_brief(spec, result, round_index=0)
        self.assertIn("No artifact was found", brief)
        self.assertIn("/tmp/agent/plate.step.py", brief)

    def test_an_undetermined_assertion_is_not_presented_as_a_defect(self):
        # Telling an agent to fix geometry that was never checked wastes a round.
        spec = a_task()
        result = SpecResult(
            spec_id=spec.id,
            entry="plate.step.py",
            results=(
                AssertionResult(
                    kind="valid_solid",
                    description="sound",
                    passed=False,
                    code=FailureCode.INSPECTION_FAILED,
                    detail="worker died",
                ),
            ),
        )
        brief = repair_brief(spec, result, round_index=0)
        self.assertIn("tooling failure rather than a defect", brief)

    def test_briefs_are_written_only_for_failing_tasks(self):
        one, two = a_task("one"), a_task("two")
        corpus = Corpus(
            name="tasks", kind=KIND_TASK, root=Path("."),
            references={"one": REFERENCE, "two": REFERENCE}, specs=(one, two),
        )
        with tempfile.TemporaryDirectory() as tmp:
            session = a_session(
                tmp, a_round(result_for(one, passing=ALL), result_for(two, passing=SOME))
            )
            written = write_briefs(corpus, session, 0)
            self.assertEqual([p.name for p in written], ["two.md"])


class PersistenceTests(unittest.TestCase):
    def test_a_session_round_trips_through_disk(self):
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "s1"
            session = a_session(
                root,
                a_round(result_for(spec, passing=SOME)),
                a_round(result_for(spec, passing=ALL)),
            )
            session.save()

            loaded = RepairSession.load(root)
            self.assertEqual(loaded.round_count, 2)
            self.assertEqual(loaded.recovered_at(), {1: {"plate"}})
            self.assertEqual(loaded.artifacts_dir, "/tmp/agent")

    def test_a_reloaded_round_keeps_its_failure_codes(self):
        # A session is a history. Losing the codes would make an old run
        # indistinguishable from a differently broken one.
        spec = a_task()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "s1"
            a_session(root, a_round(result_for(spec, passing=SOME))).save()
            loaded = RepairSession.load(root)
            codes = {a.code for a in loaded.rounds[0].results[0].failures()}
            self.assertEqual(codes, {FailureCode.COUNT_MISMATCH})

    def test_loading_a_directory_with_no_session_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError) as ctx:
                RepairSession.load(tmp)
            self.assertIn("no repair session", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
