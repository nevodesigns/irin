"""`report` must say which corpus produced a number, every time.

A stored result quoted without knowing which requirements produced it is not a
result. The difference is invisible unless something states it out loud, and
this repository shipped a headline figure with exactly that flaw: a baseline
measured against 51 models, quoted in the README, carrying no way to tell which
corpus it came from. The corpus had since grown to 57.

Nothing caught it, because no test reads prose and no check compared a stored
result to the corpus on disk. These do.
"""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from irinspec import Size, Spec, ValidSolid
from irinbench import KIND_REGRESSION, Corpus
from irinbench.corpus import KIND_TASK
from irinbench.cli import cmd_report


def a_corpus(root: Path) -> Corpus:
    spec = Spec(
        id="widget",
        prompt="a 40 x 25 x 8 mm block",
        assertions=(ValidSolid(), Size(z=8.0)),
    )
    corpus = Corpus(
        name="regression",
        kind=KIND_REGRESSION,
        root=root,
        entries={"widget": "models/widget.step.py"},
        specs=(spec,),
    )
    corpus.save()
    return corpus


def a_result(path: Path, *, fingerprint: str | None) -> Path:
    corpus_block = {"name": "regression", "kind": "regression"}
    if fingerprint is not None:
        corpus_block["fingerprint"] = fingerprint
    path.write_text(
        json.dumps(
            {
                "corpus": corpus_block,
                "started_at": "2026-08-21T02:25:27+00:00",
                "duration_s": 12.5,
                "totals": {
                    "specs": 1,
                    "specs_passing": 1,
                    "assertions": 2,
                    "assertions_passed": 2,
                    "assertions_undetermined": 0,
                },
                "rates": {"spec_pass_rate": 1.0, "assertion_pass_rate": 1.0},
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def report(result: Path, repo_root: Path, corpus: str) -> str:
    args = argparse.Namespace(result=str(result), repo_root=str(repo_root), corpus=corpus)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cmd_report(args)
    return buffer.getvalue()


class ProvenanceTests(unittest.TestCase):
    def test_a_result_with_no_fingerprint_is_marked_unquotable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_corpus(root / "corpus")
            out = report(a_result(root / "r.json", fingerprint=None), root, "corpus")
        self.assertIn("UNKNOWN", out)
        self.assertIn("Do not quote it", out)

    def test_a_matching_fingerprint_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = a_corpus(root / "corpus")
            out = report(
                a_result(root / "r.json", fingerprint=corpus.fingerprint()), root, "corpus"
            )
        self.assertIn(corpus.short_fingerprint, out)
        self.assertIn("matches the corpus in this checkout", out)

    def test_a_mismatched_fingerprint_is_called_out_with_both(self):
        # The case that matters: a real number, against requirements that are
        # no longer the ones in front of you.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = a_corpus(root / "corpus")
            out = report(a_result(root / "r.json", fingerprint="0" * 64), root, "corpus")
        self.assertIn("does NOT match", out)
        self.assertIn(corpus.short_fingerprint, out)
        self.assertIn("different requirements", out)

    def test_a_missing_corpus_still_reports_the_fingerprint(self):
        # Reading a result from elsewhere is legitimate. It just cannot be
        # compared, and saying nothing would be worse than saying that.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = report(a_result(root / "r.json", fingerprint="a" * 64), root, "no-such-corpus")
        self.assertIn("a" * 12, out)
        self.assertNotIn("matches the corpus", out)

    def test_the_numbers_still_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_corpus(root / "corpus")
            out = report(a_result(root / "r.json", fingerprint=None), root, "corpus")
        self.assertIn("specs", out)
        self.assertIn("assertions", out)

class ReportComparesAgainstTheRightCorpusTests(unittest.TestCase):
    """A sound result must not be told it is stale.

    `report` compared the stored fingerprint against a fixed default corpus
    rather than against the corpus the result names. Reporting a `tasks` result
    while the default pointed at `regression` printed "does NOT match this
    checkout" over a result that matched perfectly well.

    A warning that fires on every sound number teaches the reader to skip it,
    which costs more than having no warning at all: the day it is right, it
    looks like all the days it was wrong.
    """

    def _tasks_corpus(self, root: Path) -> Corpus:
        # Deliberately not the same spec as a_corpus. A fingerprint is a hash
        # over the specs, so two corpora holding identical requirements share
        # one, and a fixture that reused the spec would compare equal to the
        # regression corpus by accident and prove nothing.
        spec = Spec(
            id="bracket",
            prompt="an L bracket, 60 mm on the long leg",
            assertions=(ValidSolid(), Size(x=60.0)),
        )
        # No entries: a task corpus binds nothing, because the artifact is
        # whatever an agent produced for that run.
        corpus = Corpus(name="tasks", kind=KIND_TASK, root=root, specs=(spec,))
        corpus.save()
        return corpus

    def _tasks_result(self, path: Path, fingerprint: str, *, partial: bool = False) -> Path:
        path.write_text(
            json.dumps(
                {
                    "corpus": {
                        "name": "tasks",
                        "kind": "task",
                        "fingerprint": fingerprint,
                        "tasks": 28,
                    },
                    "partial": partial,
                    "started_at": "2026-08-29T06:27:22+00:00",
                    "duration_s": 21.5,
                    "totals": {
                        "specs": 21,
                        "specs_passing": 8,
                        "assertions": 115,
                        "assertions_passed": 66,
                        "assertions_undetermined": 0,
                    },
                    "rates": {"spec_pass_rate": 0.381, "assertion_pass_rate": 0.574},
                    "results": [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def _report_with_default(self, result: Path, repo_root: Path) -> str:
        # corpus=None is what the CLI now passes when --corpus is absent.
        args = argparse.Namespace(result=str(result), repo_root=str(repo_root), corpus=None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cmd_report(args)
        return buffer.getvalue()

    def test_a_tasks_result_is_compared_against_the_tasks_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmarks = root / "benchmarks"
            benchmarks.mkdir()
            # Both corpora exist, exactly as they do in the repository.
            a_corpus(benchmarks / "regression")
            tasks = self._tasks_corpus(benchmarks / "tasks")

            out = self._report_with_default(
                self._tasks_result(root / "r.json", tasks.fingerprint()), root
            )

        self.assertIn("matches the corpus in this checkout", out)
        self.assertNotIn("does NOT match", out)

    def test_a_genuinely_stale_result_is_still_caught(self):
        # The warning must keep working, or this fix traded a false alarm for
        # a missing one.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmarks = root / "benchmarks"
            benchmarks.mkdir()
            self._tasks_corpus(benchmarks / "tasks")

            out = self._report_with_default(
                self._tasks_result(root / "r.json", "0" * 64), root
            )

        self.assertIn("does NOT match", out)

    def test_an_explicit_corpus_still_wins(self):
        # Comparing a result against a named corpus on purpose is a real thing
        # to want, and the default must not take that away.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            benchmarks = root / "benchmarks"
            benchmarks.mkdir()
            a_corpus(benchmarks / "regression")
            tasks = self._tasks_corpus(benchmarks / "tasks")

            args = argparse.Namespace(
                result=str(self._tasks_result(root / "r.json", tasks.fingerprint())),
                repo_root=str(root),
                corpus="benchmarks/regression",
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                cmd_report(args)
            out = buffer.getvalue()

        self.assertIn("does NOT match", out)


class ReportSaysWhenARunWasPartialTests(unittest.TestCase):
    """`run` and `compare` both announce a partial run. `report` did not.

    A report reading "specs 8 / 21" for a corpus of 28 describes an agent that
    was never asked seven of the questions. Without the banner it reads as a
    whole run that went badly, and the two are not the same claim.
    """

    def _report(self, result: Path, repo_root: Path) -> str:
        args = argparse.Namespace(result=str(result), repo_root=str(repo_root), corpus=None)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cmd_report(args)
        return buffer.getvalue()

    def test_a_partial_result_says_so(self):
        maker = ReportComparesAgainstTheRightCorpusTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmarks").mkdir()
            corpus = maker._tasks_corpus(root / "benchmarks" / "tasks")
            out = self._report(
                maker._tasks_result(root / "r.json", corpus.fingerprint(), partial=True),
                root,
            )

        self.assertIn("PARTIAL", out)
        self.assertIn("21 of 28", out)
        self.assertIn("not comparable", out)

    def test_a_full_result_does_not(self):
        maker = ReportComparesAgainstTheRightCorpusTests()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmarks").mkdir()
            corpus = maker._tasks_corpus(root / "benchmarks" / "tasks")
            out = self._report(
                maker._tasks_result(root / "r.json", corpus.fingerprint(), partial=False),
                root,
            )

        self.assertNotIn("PARTIAL", out)


if __name__ == "__main__":
    unittest.main()
