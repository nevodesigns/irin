import tempfile
import unittest
from pathlib import Path

from irinspec import PartCount, Size, Spec, ValidSolid
from irineval import RecordedRunner, responses_from_pairs
from irinbench import (
    Corpus,
    KIND_REGRESSION,
    derive_corpus,
    derive_spec,
    failure_taxonomy,
    format_report,
    run_corpus,
)

WIDGET = "models/widget.step.py"
PANEL = "models/panel.step.py"


def facts_payload(*, size, bounds_min, bounds_max, parts, faces, edges):
    return {
        "ok": True,
        "tokens": [
            {
                "summary": {
                    "kind": "assembly",
                    "leafOccurrenceCount": parts,
                    "faceCount": faces,
                    "edgeCount": edges,
                    "bounds": {"min": list(bounds_min), "max": list(bounds_max)},
                },
                "entryFacts": {"size": list(size), "kind": "assembly"},
            }
        ],
        "errors": [],
    }


WIDGET_FACTS = facts_payload(
    size=(40.0, 25.0, 8.0),
    bounds_min=(-20.0, -12.5, 0.0),
    bounds_max=(20.0, 12.5, 8.0),
    parts=1,
    faces=6,
    edges=12,
)

ASSEMBLY_FACTS = facts_payload(
    size=(140.0, 139.6, 14.0),
    bounds_min=(-70.0, -69.8, -5.0),
    bounds_max=(70.0, 69.8, 9.0),
    parts=9,
    faces=579,
    edges=1683,
)

VALIDATE_OK = {"ok": True, "occurrenceCount": 1, "failureCount": 0, "parts": [], "errors": []}
INTERFERE_OK = {"ok": True, "clashCount": 0, "clashes": [], "stats": {}, "errors": []}

# Two overlaps that exist by design, as several fixtures in this repo do.
CLASHING = {
    "ok": False,
    "clashCount": 2,
    "clashes": [
        {"a": {"name": "hub"}, "b": {"name": "shaft"}, "volume": 60.0},
        {"a": {"name": "pin"}, "b": {"name": "boss"}, "volume": 12.0},
    ],
    "stats": {},
    "errors": [],
}


class DeriveTests(unittest.TestCase):
    def test_a_derived_spec_records_what_the_model_measures(self):
        runner = RecordedRunner(responses_from_pairs({("refs", WIDGET, "--facts"): WIDGET_FACTS}.items()))
        spec = derive_spec(WIDGET, runner)

        self.assertEqual(spec.id, "widget")
        kinds = [a.kind for a in spec.assertions]
        self.assertEqual(
            kinds, ["valid_solid", "size", "bounds", "part_count", "face_count", "edge_count"]
        )
        size = next(a for a in spec.assertions if a.kind == "size")
        self.assertEqual(size.axes(), {"x": 40.0, "y": 25.0, "z": 8.0})

    def test_interference_is_off_by_default(self):
        # It is the most expensive inspection by a wide margin.
        runner = RecordedRunner(responses_from_pairs({("refs", WIDGET, "--facts"): WIDGET_FACTS}.items()))
        kinds = [a.kind for a in derive_spec(WIDGET, runner).assertions]
        self.assertNotIn("clash_count", kinds)
        self.assertNotIn("no_interference", kinds)

    def test_enabling_interference_records_the_count_it_measures(self):
        # Never `no_interference`. Several real models overlap on purpose, so a
        # baseline asserting "no part overlaps" would fail by construction on
        # the very model it was derived from.
        runner = RecordedRunner(
            responses_from_pairs(
                {
                    ("refs", PANEL, "--facts"): ASSEMBLY_FACTS,
                    ("interfere", PANEL, "--tolerance", "1"): CLASHING,
                }.items()
            )
        )
        spec = derive_spec(PANEL, runner, include_interference=True)
        clash = next(a for a in spec.assertions if a.kind == "clash_count")
        self.assertEqual(clash.value, 2)
        self.assertNotIn("no_interference", [a.kind for a in spec.assertions])

    def test_a_derived_clash_count_passes_against_the_model_it_came_from(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {
                    ("refs", PANEL, "--facts"): ASSEMBLY_FACTS,
                    ("interfere", PANEL, "--tolerance", "1"): CLASHING,
                    ("validate", PANEL): VALIDATE_OK,
                }.items()
            )
        )
        spec = derive_spec(PANEL, runner, include_interference=True)
        corpus = Corpus(
            name="r", kind=KIND_REGRESSION, root=Path("."), entries={spec.id: PANEL}, specs=(spec,)
        )
        self.assertEqual(run_corpus(corpus, runner).passing, 1)

    def test_the_prompt_says_it_is_a_baseline_not_a_task(self):
        # A derived spec must never be mistaken for an authored agent task: the
        # model passes it by construction.
        runner = RecordedRunner(responses_from_pairs({("refs", WIDGET, "--facts"): WIDGET_FACTS}.items()))
        spec = derive_spec(WIDGET, runner)
        self.assertIn("Regression baseline", spec.prompt)
        self.assertIn("passes them by construction", spec.notes)

    def test_a_derived_spec_passes_against_the_model_it_came_from(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {
                    ("refs", WIDGET, "--facts"): WIDGET_FACTS,
                    ("validate", WIDGET): VALIDATE_OK,
                }.items()
            )
        )
        spec = derive_spec(WIDGET, runner)
        corpus = Corpus(
            name="r",
            kind=KIND_REGRESSION,
            root=Path("."),
            entries={spec.id: WIDGET},
            specs=(spec,),
        )
        run = run_corpus(corpus, runner)
        self.assertEqual(run.passing, 1)
        self.assertEqual(run.assertions_undetermined, 0)

    def test_an_unmeasurable_entry_is_reported_not_dropped(self):
        # A corpus that silently shrinks when the engine breaks hides the
        # breakage behind a smaller, still-green run.
        runner = RecordedRunner(responses_from_pairs({("refs", WIDGET, "--facts"): WIDGET_FACTS}.items()))
        with tempfile.TemporaryDirectory() as tmp:
            corpus, failures = derive_corpus("r", [WIDGET, PANEL], runner, Path(tmp))
        self.assertEqual(len(corpus.specs), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], PANEL)
        self.assertEqual(corpus.provenance["entries_failed"], 1)


class RunTests(unittest.TestCase):
    def _corpus(self, spec: Spec, entry: str = WIDGET) -> Corpus:
        return Corpus(
            name="regression",
            kind=KIND_REGRESSION,
            root=Path("."),
            entries={spec.id: entry},
            specs=(spec,),
        )

    def test_drift_in_one_dimension_fails_the_run(self):
        # The corpus says 8 mm thick; the model now measures 10.
        drifted = facts_payload(
            size=(40.0, 25.0, 10.0),
            bounds_min=(-20.0, -12.5, 0.0),
            bounds_max=(20.0, 12.5, 10.0),
            parts=1,
            faces=6,
            edges=12,
        )
        runner = RecordedRunner(
            responses_from_pairs(
                {("refs", WIDGET, "--facts"): drifted, ("validate", WIDGET): VALIDATE_OK}.items()
            )
        )
        spec = Spec(
            id="widget",
            prompt="baseline",
            assertions=(ValidSolid(), Size(x=40.0, y=25.0, z=8.0), PartCount(value=1)),
        )
        run = run_corpus(self._corpus(spec), runner)
        self.assertEqual(run.passing, 0)
        self.assertEqual(run.with_defects, 1)
        self.assertEqual(run.with_undetermined, 0)
        self.assertAlmostEqual(run.assertion_pass_rate, 2 / 3)

    def test_totals_serialize_with_provenance(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {("refs", WIDGET, "--facts"): WIDGET_FACTS, ("validate", WIDGET): VALIDATE_OK}.items()
            )
        )
        spec = Spec(id="widget", prompt="baseline", assertions=(ValidSolid(), Size(x=40.0)))
        data = run_corpus(self._corpus(spec), runner).to_dict()
        self.assertEqual(data["corpus"], {"name": "regression", "kind": "regression"})
        self.assertIn("irin_version", data["environment"])
        self.assertEqual(data["totals"]["specs"], 1)
        self.assertEqual(data["rates"]["spec_pass_rate"], 1.0)

    def test_a_broken_inspection_is_counted_apart_from_a_defect(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {
                    ("refs", WIDGET, "--facts"): WIDGET_FACTS,
                    ("validate", WIDGET): {"ok": False, "errors": [{"message": "boom"}]},
                }.items()
            )
        )
        spec = Spec(id="widget", prompt="baseline", assertions=(ValidSolid(), Size(x=40.0)))
        run = run_corpus(self._corpus(spec), runner)
        self.assertEqual(run.with_defects, 0)
        self.assertEqual(run.with_undetermined, 1)
        self.assertEqual(run.assertions_undetermined, 1)


class ReportTests(unittest.TestCase):
    def _failing_run(self):
        drifted = facts_payload(
            size=(40.0, 25.0, 10.0),
            bounds_min=(-20.0, -12.5, 0.0),
            bounds_max=(20.0, 12.5, 10.0),
            parts=1,
            faces=6,
            edges=12,
        )
        runner = RecordedRunner(
            responses_from_pairs(
                {("refs", WIDGET, "--facts"): drifted, ("validate", WIDGET): VALIDATE_OK}.items()
            )
        )
        spec = Spec(
            id="widget",
            prompt="baseline",
            assertions=(ValidSolid(), Size(x=40.0, y=25.0, z=8.0)),
        )
        corpus = Corpus(
            name="regression", kind=KIND_REGRESSION, root=Path("."), entries={"widget": WIDGET}, specs=(spec,)
        )
        return run_corpus(corpus, runner)

    def test_the_report_carries_the_measured_number_not_just_a_count(self):
        text = format_report(self._failing_run())
        self.assertIn("widget", text)
        self.assertIn("dimension_out_of_tolerance", text)
        # The point of the whole project: a number you can act on.
        self.assertIn("mm", text)

    def test_the_taxonomy_separates_reasons(self):
        counts = failure_taxonomy(self._failing_run())
        self.assertEqual(counts, {"dimension_out_of_tolerance": 1})

    def test_a_clean_run_says_so(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {("refs", WIDGET, "--facts"): WIDGET_FACTS, ("validate", WIDGET): VALIDATE_OK}.items()
            )
        )
        spec = Spec(id="widget", prompt="baseline", assertions=(ValidSolid(), Size(x=40.0)))
        corpus = Corpus(
            name="regression", kind=KIND_REGRESSION, root=Path("."), entries={"widget": WIDGET}, specs=(spec,)
        )
        self.assertIn("no failures", format_report(run_corpus(corpus, runner)))


if __name__ == "__main__":
    unittest.main()
