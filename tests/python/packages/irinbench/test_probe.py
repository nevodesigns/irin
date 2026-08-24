"""Probing: does a task reject a wrong answer?

`verify` proves a task is satisfiable and cannot see the opposite failure, where
a task's assertions are so loose that things which should fail pass. The vee
block asked for a 90 degree groove and asserted size, bounds, part count and the
absence of holes, all of which a plain cube satisfies, and nothing in the corpus
noticed until an accident found it.

The wrong answer is deliberately the most charitable one available: a sound
solid with the reference's own bounding size and nothing else. A task that
cannot tell that from the real part is checking extents.
"""

import unittest
from pathlib import Path

from irinspec import HoleCount, PartCount, Size, Spec, ValidSolid, Volume
from irineval import RecordedRunner, responses_from_pairs
from irinbench import KIND_REGRESSION, KIND_TASK, Corpus, CorpusError
from irinbench.probe import format_probe, probe_corpus

REFERENCE = "models/step/parts/widget.step.py"


def facts_payload(size=(40.0, 25.0, 8.0), bounds_min=(-20.0, -12.5, 0.0)):
    bounds_max = tuple(bounds_min[i] + size[i] for i in range(3))
    return {
        "ok": True,
        "tokens": [
            {
                "summary": {
                    "kind": "part",
                    "leafOccurrenceCount": 1,
                    "faceCount": 6,
                    "edgeCount": 12,
                    "bounds": {"min": list(bounds_min), "max": list(bounds_max)},
                },
                "entryFacts": {"size": list(size), "kind": "part"},
            }
        ],
        "errors": [],
    }


class FakeRunner(RecordedRunner):
    """Answers as if the artifact under test were a plain box."""

    def __init__(self, *, holes=0, volume=8000.0):
        table = {
            ("refs", "widget.step.py", "--facts"): facts_payload(),
            ("validate", "widget.step.py"): {
                "ok": True, "volume": volume, "occurrenceCount": 1,
                "failureCount": 0, "parts": [], "errors": [],
            },
            ("features", "widget.step.py"): {
                "ok": True,
                "features": [
                    {
                        "ref": "o1", "name": "p", "kind": "hole", "diameter": 6.0,
                        "axis": [0.0, 0.0, 1.0], "position": [0.0, 0.0, 0.0],
                        "depth": 8.0, "through": True, "complete": True, "faceCount": 1,
                    }
                ] * holes,
                "patterns": [], "errors": [],
            },
        }
        super().__init__(responses_from_pairs(table.items()))


def a_corpus(spec: Spec, *, kind=KIND_TASK, reference=REFERENCE) -> Corpus:
    return Corpus(
        name="tasks",
        kind=kind,
        root=Path("."),
        references={spec.id: reference} if reference else {},
        specs=(spec,),
    )


def run_probe(spec: Spec, *, holes=0, volume=8000.0, corpus=None):
    reference_runner = RecordedRunner(
        responses_from_pairs({("refs", REFERENCE, "--facts"): facts_payload()}.items())
    )
    return probe_corpus(
        corpus or a_corpus(spec),
        lambda _dir: FakeRunner(holes=holes, volume=volume),
        reference_runner,
    )


class ProbeTests(unittest.TestCase):
    def test_a_task_checking_only_extents_is_reported_as_weak(self):
        # Exactly the vee block's original shape: everything it asserts is true
        # of a plain box.
        spec = Spec(
            id="widget",
            prompt="a 40 x 25 x 8 block with a groove down the top",
            assertions=(ValidSolid(), PartCount(value=1), Size(x=40.0, y=25.0, z=8.0)),
        )
        report = run_probe(spec)
        self.assertFalse(report.ok)
        self.assertEqual([r.spec_id for r in report.vacuous], ["widget"])
        self.assertIn("a plain box passes this task", report.results[0].summary_line())

    def test_a_volume_assertion_rescues_it(self):
        # The fix that closed the real defect: the box has more material.
        spec = Spec(
            id="widget",
            prompt="a 40 x 25 x 8 block with a groove down the top",
            assertions=(
                ValidSolid(),
                Size(x=40.0, y=25.0, z=8.0),
                Volume(value=6000.0),
            ),
        )
        report = run_probe(spec, volume=8000.0)
        self.assertTrue(report.ok)
        self.assertIn("rejected by volume", report.results[0].summary_line())

    def test_a_feature_assertion_also_rejects_it(self):
        spec = Spec(
            id="widget",
            prompt="a plate with two 6 mm holes",
            assertions=(ValidSolid(), HoleCount(value=2, diameter=6.0)),
        )
        report = run_probe(spec, holes=0)
        self.assertTrue(report.ok)
        self.assertIn("hole_count", report.results[0].summary_line())

    def test_the_report_names_what_did_the_rejecting(self):
        # So an author can see which assertion is carrying the task.
        spec = Spec(
            id="widget",
            prompt="a plate with two 6 mm holes",
            assertions=(HoleCount(value=2, diameter=6.0),),
        )
        text = format_probe(run_probe(spec))
        self.assertIn("rejected", text)
        self.assertIn("every task rejects it", text)

    def test_a_weak_task_report_suggests_the_fix(self):
        spec = Spec(
            id="widget",
            prompt="a block with a groove",
            assertions=(Size(x=40.0),),
        )
        text = format_probe(run_probe(spec))
        self.assertIn("volume", text)
        self.assertIn("check extents rather than", text)

    def test_a_task_with_no_reference_is_skipped_not_counted(self):
        # There is nothing to size a box from, which is not evidence either way.
        spec = Spec(id="widget", prompt="p", assertions=(Size(x=40.0),))
        report = run_probe(spec, corpus=a_corpus(spec, reference=None))
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(report.vacuous, ())
        self.assertIn("no reference", report.results[0].error)

    def test_probing_a_regression_corpus_is_refused(self):
        # Its specs record what a model measures, so "a wrong answer" is not a
        # meaningful question to ask of them.
        spec = Spec(id="widget", prompt="p", assertions=(Size(x=40.0),))
        corpus = Corpus(
            name="regression", kind=KIND_REGRESSION, root=Path("."),
            entries={"widget": REFERENCE}, specs=(spec,),
        )
        with self.assertRaises(CorpusError) as ctx:
            run_probe(spec, corpus=corpus)
        self.assertIn("regression", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
