"""End-to-end tests against the real inspect worker and a real CAD kernel.

The recorded fixtures in ``fixtures.py`` make the unit tests fast and
deterministic, and they would go on passing forever if the CLI's output changed
underneath them. These tests are the tie back to reality: they build actual
geometry, drive the actual worker, and assert the evaluator reaches the right
verdict from whatever the CLI really returns today.

Skipped when build123d is unavailable, so the evaluator's own suite still runs
in an environment without a CAD kernel.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from irinspec import (
    BoltCircle,
    BossCount,
    Bounds,
    FeatureSpacing,
    FilletCount,
    Volume,
    ClashCount,
    HoleCount,
    Distance,
    EdgeCount,
    FaceCount,
    NoInterference,
    PartCount,
    Size,
    Spec,
    Tolerance,
    ValidSolid,
)
from irineval import FailureCode, WorkerRunner, evaluate, inspect_argv

REPO_ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = REPO_ROOT / "skills" / "cad" / "scripts" / "inspect"

try:  # pragma: no cover - environment probe
    import build123d  # noqa: F401

    HAVE_CAD = True
except Exception:  # pragma: no cover - environment probe
    HAVE_CAD = False


WIDGET_SOURCE = textwrap.dedent(
    """
    from build123d import Align, Box, BuildPart

    LENGTH = 40.0
    WIDTH = 25.0
    HEIGHT = 8.0


    def gen_step():
        with BuildPart() as part:
            Box(LENGTH, WIDTH, HEIGHT, align=(Align.CENTER, Align.CENTER, Align.MIN))
        result = part.part
        result.label = "widget"
        return result
    """
).strip()


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class WorkerCommandCoverageTests(unittest.TestCase):
    """The worker must answer every command the evaluator can emit.

    `validate` and `interfere` reached the CLI after the worker dispatch was
    written and were missing from it, so the worker answered
    "Unsupported inspect command" for two of the eight assertion kinds. Nothing
    caught that, because the worker's own tests never asked for them.
    """

    def test_the_worker_answers_every_command_the_evaluator_emits(self):
        from inspect_refs.cli import inspect_command_result  # type: ignore

        samples = (
            ValidSolid(),
            Volume(value=1.0),
            Size(x=1.0),
            Bounds(min=(0.0, 0.0, 0.0)),
            PartCount(value=1),
            FaceCount(value=1),
            EdgeCount(value=1),
            NoInterference(),
            ClashCount(value=0),
            HoleCount(value=1),
            BossCount(value=1),
            FeatureSpacing(diameter=6.0, value=60.0),
            FilletCount(value=1),
            BoltCircle(diameter=60.0, count=6),
            Distance(from_ref="#f1", to_ref="#f2", axis="z", value=1.0),
        )
        commands = {inspect_argv(a, "does/not/exist.step.py")[0] for a in samples}

        for command in sorted(commands):
            _code, result = inspect_command_result([command, "does/not/exist.step.py"])
            messages = " ".join(
                str(e.get("message", "")) for e in result.get("errors", []) if isinstance(e, dict)
            )
            self.assertNotIn(
                "Unsupported inspect command",
                messages,
                f"the worker cannot answer {command!r}, so assertions using it would "
                "come back undetermined for every model",
            )


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class RealEvaluationTests(unittest.TestCase):
    """Build real geometry, evaluate it, and check the verdict."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls._tmp.name)
        models = cls.workspace / "models"
        models.mkdir()
        (models / "widget.step.py").write_text(WIDGET_SOURCE + "\n", encoding="utf-8")
        cls.entry = "models/widget.step.py"
        cls.runner = WorkerRunner(cwd=cls.workspace, inspect_launcher=LAUNCHER)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.runner.close()
        cls._tmp.cleanup()

    def _spec(self, *assertions) -> Spec:
        return Spec(id="widget", prompt="a 40 x 25 x 8 mm block", assertions=assertions)

    def test_a_correct_model_passes_across_all_four_inspections(self):
        spec = self._spec(
            ValidSolid(),
            Size(x=40.0, y=25.0, z=8.0, tolerance=Tolerance.symmetric(0.05)),
            Bounds(min=(-20.0, -12.5, 0.0), max=(20.0, 12.5, 8.0)),
            PartCount(value=1),
            NoInterference(),
        )
        result = evaluate(spec, self.entry, self.runner)
        self.assertTrue(result.ok, [f.detail for f in result.failures()])
        self.assertEqual(result.undetermined_count, 0)

    def test_a_wrong_dimension_fails_with_the_real_measured_number(self):
        # The model is 8 mm thick. Asking for 10 must fail by exactly 2.
        spec = self._spec(Size(z=10.0, tolerance=Tolerance.symmetric(0.1)))
        result = evaluate(spec, self.entry, self.runner)
        self.assertFalse(result.ok)
        failure = result.failures()[0]
        self.assertEqual(failure.code, FailureCode.DIMENSION_OUT_OF_TOLERANCE)
        self.assertAlmostEqual(failure.actual["z"], 8.0)
        self.assertAlmostEqual(failure.deviation, -2.0)
        self.assertEqual(result.defect_count, 1)
        self.assertEqual(result.undetermined_count, 0)

    def test_a_wrong_part_count_fails_against_real_topology(self):
        result = evaluate(self._spec(PartCount(value=4)), self.entry, self.runner)
        failure = result.failures()[0]
        self.assertEqual(failure.code, FailureCode.COUNT_MISMATCH)
        self.assertEqual(failure.actual, 1)

    def test_an_unresolvable_selector_is_undetermined_not_a_defect(self):
        spec = self._spec(Distance(from_ref="#f999", to_ref="#f1", axis="z", value=8.0))
        result = evaluate(spec, self.entry, self.runner)
        failure = result.failures()[0]
        self.assertEqual(failure.code, FailureCode.SELECTOR_UNRESOLVED)
        self.assertEqual(result.defect_count, 0)

    def test_a_missing_model_is_undetermined_for_every_assertion(self):
        spec = self._spec(ValidSolid(), Size(x=40.0))
        result = evaluate(spec, "models/absent.step.py", self.runner)
        self.assertEqual(result.undetermined_count, 2)
        self.assertEqual(result.defect_count, 0)

    def test_the_recorded_facts_fixture_still_matches_the_live_shape(self):
        # Guards the unit tests: if the CLI changes these field names, the
        # recordings go stale and every fast test keeps passing on fiction.
        import fixtures

        response = self.runner.run(["refs", self.entry, "--facts"])
        self.assertTrue(response.ok)
        live = response.result["tokens"][0]
        recorded = fixtures.BLOCK_FACTS["tokens"][0]
        self.assertEqual(set(recorded["summary"]) - set(live["summary"]), set())
        self.assertEqual(set(recorded["entryFacts"]) - set(live["entryFacts"]), set())

    def test_the_recorded_validate_fixture_still_matches_the_live_shape(self):
        import fixtures

        response = self.runner.run(["validate", self.entry])
        self.assertTrue(response.ok)
        self.assertEqual(
            set(fixtures.BLOCK_VALIDATE) - set(response.result), set()
        )

    def test_the_recorded_interfere_fixture_still_matches_the_live_shape(self):
        import fixtures

        response = self.runner.run(["interfere", self.entry, "--tolerance", "1"])
        self.assertTrue(response.ok)
        self.assertEqual(
            set(fixtures.BLOCK_INTERFERE) - set(response.result), set()
        )

    def test_one_worker_serves_many_inspections(self):
        # The point of the worker: the kernel import is paid once.
        before = self.runner._next_id
        evaluate(
            self._spec(ValidSolid(), Size(x=40.0), PartCount(value=1), NoInterference()),
            self.entry,
            self.runner,
        )
        self.assertEqual(self.runner._next_id - before, 3)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class TimeoutTests(unittest.TestCase):
    """A request that will not come back must not stop the run.

    One assembly in the reference corpus held the CPU for over twenty minutes
    inside a single `validate` call. Without a budget the benchmark stops there
    forever, and a run that never finishes reports nothing at all.
    """

    def test_an_over_budget_request_is_abandoned_and_reported(self):
        from irineval import InspectTimeout

        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models"
            models.mkdir()
            (models / "widget.step.py").write_text(WIDGET_SOURCE + "\n", encoding="utf-8")
            # Small enough that no real inspection could finish inside it.
            runner = WorkerRunner(cwd=Path(tmp), inspect_launcher=LAUNCHER, timeout_s=0.05)
            try:
                with self.assertRaises(InspectTimeout) as ctx:
                    runner.run(["validate", "models/widget.step.py"])
                self.assertIn("undetermined", str(ctx.exception))
                self.assertEqual(runner.timeouts, 1)
            finally:
                runner.close()

    def test_the_evaluator_turns_a_timeout_into_undetermined_not_a_defect(self):
        from irinspec import Size, Spec, ValidSolid

        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models"
            models.mkdir()
            (models / "widget.step.py").write_text(WIDGET_SOURCE + "\n", encoding="utf-8")
            runner = WorkerRunner(cwd=Path(tmp), inspect_launcher=LAUNCHER, timeout_s=0.05)
            try:
                spec = Spec(
                    id="widget",
                    prompt="a 40 x 25 x 8 mm block",
                    assertions=(ValidSolid(), Size(x=40.0)),
                )
                result = evaluate(spec, "models/widget.step.py", runner)
                self.assertEqual(result.defect_count, 0)
                self.assertEqual(result.undetermined_count, 2)
                self.assertIn("exceeded", result.failures()[0].detail)
            finally:
                runner.close()

    def test_no_budget_by_default(self):
        # An interactive caller checking one model should wait for the answer.
        with tempfile.TemporaryDirectory() as tmp:
            runner = WorkerRunner(cwd=Path(tmp), inspect_launcher=LAUNCHER)
            self.assertIsNone(runner.timeout_s)
            runner.close()
