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


if __name__ == "__main__":
    unittest.main()
