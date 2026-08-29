"""Comparing results, and refusing to compare what is not comparable.

One result is a measurement. Several are a benchmark, but only if they were
scored against the same requirements. Two runs of "the tasks corpus" taken a
month apart can describe entirely different sets of tasks, and a table lining
them up anyway would manufacture a comparison that does not exist.

So the grouping key is the corpus fingerprint, never the corpus name.
"""

import json
import tempfile
import unittest
from pathlib import Path

from irinbench.compare import (
    StoredResult,
    format_comparison,
    group_by_corpus,
    load_results,
)


def write_result(
    path: Path,
    *,
    agent: str,
    fingerprint: str,
    specs=10,
    passing=7,
    assertions=40,
    assertions_passed=35,
    undetermined=0,
    name="tasks",
    corpus_tasks=None,
    partial=False,
) -> Path:
    corpus = {"name": name, "kind": "task"}
    if fingerprint is not None:
        corpus["fingerprint"] = fingerprint
    if corpus_tasks is not None:
        corpus["tasks"] = corpus_tasks
    path.write_text(
        json.dumps(
            {
                "corpus": corpus,
                "agent": agent,
                "partial": partial,
                "started_at": "2026-08-22T00:00:00+00:00",
                "duration_s": 10.0,
                "environment": {"irin_version": "0.4.20"},
                "totals": {
                    "specs": specs,
                    "specs_passing": passing,
                    "assertions": assertions,
                    "assertions_passed": assertions_passed,
                    "assertions_undetermined": undetermined,
                },
                "rates": {},
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    return path


class GroupingTests(unittest.TestCase):
    def test_results_group_by_fingerprint_not_by_name(self):
        # Both call themselves "tasks". They are not the same benchmark.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "a.json", agent="alpha", fingerprint="a" * 64)
            write_result(root / "b.json", agent="beta", fingerprint="b" * 64)
            groups = group_by_corpus(load_results(root.glob("*.json")))
        self.assertEqual(len(groups), 2)

    def test_results_on_one_corpus_are_ranked_best_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "a.json", agent="worse", fingerprint="a" * 64, passing=3)
            write_result(root / "b.json", agent="better", fingerprint="a" * 64, passing=9)
            groups = group_by_corpus(load_results(root.glob("*.json")))
            labels = [r.label for r in groups["a" * 64]]
        self.assertEqual(labels, ["better", "worse"])

    def test_a_result_with_no_fingerprint_is_kept_out_of_every_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "a.json", agent="named", fingerprint="a" * 64)
            write_result(root / "old.json", agent="legacy", fingerprint=None)
            text = format_comparison(load_results(root.glob("*.json")))
        self.assertIn("no corpus fingerprint recorded", text)
        self.assertIn("old.json", text)

    def test_two_corpora_are_flagged_as_not_comparable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "a.json", agent="alpha", fingerprint="a" * 64)
            write_result(root / "b.json", agent="beta", fingerprint="b" * 64)
            text = format_comparison(load_results(root.glob("*.json")))
        self.assertIn("NOT comparable", text)

    def test_one_corpus_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "a.json", agent="alpha", fingerprint="a" * 64)
            write_result(root / "b.json", agent="beta", fingerprint="a" * 64)
            text = format_comparison(load_results(root.glob("*.json")))
        self.assertNotIn("NOT comparable", text)


class ReadingTests(unittest.TestCase):
    def test_an_agent_name_labels_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_result(
                Path(tmp) / "r.json", agent="gemini-2.5-pro", fingerprint="a" * 64
            )
            self.assertEqual(StoredResult.load(path).label, "gemini-2.5-pro")

    def test_a_result_with_no_agent_falls_back_to_its_filename(self):
        # Older results predate the field. A filename is worse than a name and
        # far better than a blank row.
        with tempfile.TemporaryDirectory() as tmp:
            path = write_result(Path(tmp) / "mystery.json", agent="", fingerprint="a" * 64)
            self.assertEqual(StoredResult.load(path).label, "mystery")

    def test_rates_come_from_the_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_result(
                Path(tmp) / "r.json", agent="x", fingerprint="a" * 64,
                specs=8, passing=6, assertions=20, assertions_passed=15,
            )
            result = StoredResult.load(path)
        self.assertAlmostEqual(result.spec_rate, 0.75)
        self.assertAlmostEqual(result.assertion_rate, 0.75)

    def test_unrelated_json_in_the_directory_is_skipped(self):
        # A results directory collects things over time. Refusing to compare
        # anything because one file is not a result would be the wrong trade.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_result(root / "good.json", agent="x", fingerprint="a" * 64)
            (root / "notes.json").write_text("[1, 2, 3]", encoding="utf-8")
            (root / "broken.json").write_text("{oops", encoding="utf-8")
            self.assertEqual(len(load_results(root.glob("*.json"))), 1)

    def test_an_empty_set_says_so_rather_than_crashing(self):
        self.assertIn("no results", format_comparison([]))



class GroupHeaderTests(unittest.TestCase):
    """The header describes the corpus, not whichever result sorted first.

    Rows are sorted best first. A partial run that scored well therefore sat at
    the head of its group, and the group announced "21 task(s) each" for a
    corpus of 28: wrong about every row in it, including the partial one, whose
    own row said 21 for a different reason.
    """

    def _result(self, label, *, specs, passing, partial, corpus_tasks=28):
        from irinbench.compare import StoredResult

        return StoredResult(
            path=Path(f"{label}.json"),
            corpus_name="tasks",
            corpus_kind="task",
            fingerprint="f" * 64,
            agent=label,
            started_at="2026-08-29T06:00:00+00:00",
            specs=specs,
            specs_passing=passing,
            assertions=specs * 5,
            assertions_passed=passing * 5,
            assertions_undetermined=0,
            irin_version="0.4.20",
            corpus_tasks=corpus_tasks,
            partial=partial,
        )

    def test_the_header_states_the_corpus_size_not_a_partial_count(self):
        from irinbench.compare import format_comparison

        out = format_comparison([
            self._result("fast partial", specs=21, passing=8, partial=True),
            self._result("full run", specs=28, passing=4, partial=False),
        ])

        self.assertIn("28 task(s) in the corpus", out)
        self.assertNotIn("21 task(s)", out)

    def test_each_is_claimed_only_when_it_is_true(self):
        from irinbench.compare import format_comparison

        mixed = format_comparison([
            self._result("partial", specs=21, passing=8, partial=True),
            self._result("full", specs=28, passing=4, partial=False),
        ])
        self.assertNotIn("each", mixed)

        uniform = format_comparison([
            self._result("a", specs=28, passing=4, partial=False),
            self._result("b", specs=28, passing=3, partial=False),
        ])
        self.assertIn("each", uniform)

    def test_a_partial_row_is_labelled(self):
        from irinbench.compare import format_comparison

        out = format_comparison([self._result("gem", specs=21, passing=8, partial=True)])
        self.assertIn("(partial)", out)


class ThinResultTests(unittest.TestCase):
    """A run covering too little of the corpus is not a comparable row.

    The real one: a token-metered free tier let five of twenty-eight tasks
    through. `compare` printed "0 / 5   0.0%" in the same column of percentages
    as the complete runs, labelled only "(partial)". A rate printed in a column
    of rates is read as one, however it is labelled.
    """

    def _table(self, tmp: Path) -> str:
        write_result(
            tmp / "full.json",
            agent="complete model",
            fingerprint="abc123",
            specs=28,
            passing=7,
            corpus_tasks=28,
        )
        write_result(
            tmp / "thin.json",
            agent="throttled model",
            fingerprint="abc123",
            specs=5,
            passing=0,
            assertions=27,
            assertions_passed=0,
            corpus_tasks=28,
            partial=True,
        )
        return format_comparison(load_results(tmp.glob("*.json")))

    def test_a_thin_run_is_moved_out_of_the_ranked_table(self):
        with tempfile.TemporaryDirectory() as d:
            table = self._table(Path(d))
        self.assertIn("too thin to compare", table)
        # Listed, because deleting it would hide that the attempt was made.
        self.assertIn("throttled model", table)

    def test_a_thin_run_is_not_given_a_percentage(self):
        with tempfile.TemporaryDirectory() as d:
            table = self._table(Path(d))
        thin_line = next(
            line for line in table.splitlines() if "throttled model" in line
        )
        self.assertNotIn("%", thin_line)
        self.assertIn("5 of 28 tasks", thin_line)

    def test_the_substantial_run_keeps_its_row(self):
        with tempfile.TemporaryDirectory() as d:
            table = self._table(Path(d))
        full_line = next(line for line in table.splitlines() if "complete model" in line)
        self.assertIn("25.0%", full_line)

    def test_a_partial_covering_most_of_the_corpus_stays_comparable(self):
        # 23 of 28 is worth reading. Demoting it would make the rule noise on
        # the ordinary case of a run that lost a few tasks.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            write_result(
                tmp / "most.json",
                agent="mostly complete",
                fingerprint="abc123",
                specs=23,
                passing=0,
                corpus_tasks=28,
                partial=True,
            )
            table = format_comparison(load_results(tmp.glob("*.json")))
        self.assertNotIn("too thin", table)
        self.assertIn("(partial)", table)

    def test_a_result_that_does_not_record_corpus_size_is_not_demoted(self):
        # Older results predate the field. Absence of evidence is not thinness.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            write_result(
                tmp / "old.json", agent="legacy", fingerprint="abc123", specs=5, passing=0
            )
            table = format_comparison(load_results(tmp.glob("*.json")))
        self.assertNotIn("too thin", table)


if __name__ == "__main__":
    unittest.main()
