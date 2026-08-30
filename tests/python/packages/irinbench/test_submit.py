"""Driving an agent, and telling silence apart from an outage.

The distinction is load-bearing and was learned the hard way. A free-tier key
ran out of quota two thirds of the way through the first real run, and eight
tasks came back empty. Scored as missing artifacts they would have read as eight
failures by the model, when the model was never asked.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from irinspec import Size, Spec
from irinbench import KIND_REGRESSION, KIND_TASK, Corpus, CorpusError
from irinbench.submit import UNREACHABLE_EXIT, format_submissions, strip_fences, submit_corpus



# Commands the agent stands in for, spelled so they mean the same thing on
# every platform. `submit` runs them with shell=True, and on Windows that is
# cmd.exe rather than sh: `echo 'x = 1'` prints the quotes there, and `true` is
# not a command at all. Both of those were in this file. The first failed the
# Windows job on every commit for three days; the second passed for the wrong
# reason, because a missing command also exits non-zero with no output.
_PY = f'"{sys.executable}"'
EMITS_SOURCE = f"{_PY} -c \"print('x = 1')\""
SAYS_NOTHING = f"{_PY} -c \"pass\""
#: Answers one task and reports the other as never reached, decided from the
#: prompt on stdin. The previous version was a POSIX shell conditional that
#: cmd.exe cannot run, and it tested against a flag file nothing created, so
#: both tasks landed in the same bucket and the separation this names was
#: never exercised on any platform.
UNREACHABLE_FOR_ONE = (
    f"{_PY} -c \"import sys; sys.exit(75 if 'never' in sys.stdin.read() else 0)\""
)


def a_corpus(*ids: str, kind=KIND_TASK) -> Corpus:
    specs = tuple(
        Spec(id=i, prompt=f"a part called {i}", assertions=(Size(x=10.0),)) for i in ids
    )
    return Corpus(
        name="tasks", kind=kind, root=Path("."),
        references={i: "models/x.step.py" for i in ids}, specs=specs,
    )


class FenceTests(unittest.TestCase):
    def test_a_wrapping_fence_is_stripped(self):
        # A formatting habit, not a modelling failure.
        self.assertEqual(strip_fences("```python\nx = 1\n```"), "x = 1")

    def test_source_without_a_fence_is_untouched(self):
        self.assertEqual(strip_fences("x = 1"), "x = 1")


class SubmitTests(unittest.TestCase):
    def test_output_becomes_one_artifact_per_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(a_corpus("alpha"), EMITS_SOURCE, tmp)
            self.assertTrue(results[0].ok)
            self.assertEqual((Path(tmp) / "alpha.step.py").read_text().strip(), "x = 1")

    def test_an_agent_that_answers_with_nothing_is_a_real_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(a_corpus("alpha"), SAYS_NOTHING, tmp)
        self.assertFalse(results[0].ok)
        self.assertTrue(results[0].answered_empty)
        self.assertFalse(results[0].unreachable)

    def test_an_agent_that_could_not_be_reached_is_not_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(a_corpus("alpha"), f"exit {UNREACHABLE_EXIT}", tmp)
        self.assertTrue(results[0].unreachable)
        self.assertFalse(results[0].answered_empty)

    def test_the_report_separates_the_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(
                a_corpus("asked", "never"),
                UNREACHABLE_FOR_ONE,
                tmp,
            )
            text = format_submissions(results, tmp)
        # Both halves, or the test passes while checking only one of them.
        self.assertIn("answered with nothing", text)
        self.assertIn("NEVER ASKED", text)
        self.assertTrue(results[1].unreachable, "the refused task was not recorded as such")
        self.assertTrue(results[0].answered_empty)

    def test_an_unreachable_run_warns_against_scoring_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(a_corpus("alpha"), f"exit {UNREACHABLE_EXIT}", tmp)
            text = format_submissions(results, tmp)
        self.assertIn("NEVER ASKED", text)
        self.assertIn("report the", text)
        self.assertIn("outage", text)

    def test_only_limits_which_tasks_are_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = submit_corpus(a_corpus("alpha", "beta"), EMITS_SOURCE, tmp, only=["beta"])
        self.assertEqual([r.task_id for r in results], ["beta"])

    def test_a_regression_corpus_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError):
                submit_corpus(a_corpus("alpha", kind=KIND_REGRESSION), SAYS_NOTHING, tmp)


if __name__ == "__main__":
    unittest.main()
