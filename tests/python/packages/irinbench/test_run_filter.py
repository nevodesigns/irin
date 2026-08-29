"""The --only filter, and what it must refuse."""

from __future__ import annotations

import unittest


class OnlyFilterTests(unittest.TestCase):
    """A filter that selects nothing is a typo, not an instruction.

    ``--only`` takes a space-separated list. A comma-separated one arrives as a
    single token naming no task, and the run used to write a well-formed result
    file reporting 0 of 28 attempted. That reads as an answer. It can be filed,
    quoted and compared, and nothing about it looks wrong.
    """

    def _corpus(self):
        from irinbench.run import reject_unknown_ids

        return reject_unknown_ids

    def test_an_unknown_id_is_refused(self):
        from irinbench.corpus import CorpusError

        reject = self._corpus()
        corpus = _FakeCorpus("tasks", ["vee-block", "shaft-collar"])

        with self.assertRaises(CorpusError) as ctx:
            reject(corpus, {"vee-block,shaft-collar"})

        message = str(ctx.exception)
        self.assertIn("vee-block,shaft-collar", message)
        # The message must name the actual mistake, or the reader retries the
        # same comma list with a different id.
        self.assertIn("space-separated", message)

    def test_a_known_subset_is_allowed(self):
        self._corpus()(_FakeCorpus("tasks", ["a", "b", "c"]), {"a", "c"})

    def test_no_filter_is_allowed(self):
        self._corpus()(_FakeCorpus("tasks", ["a"]), None)

    def test_every_unknown_id_is_named_at_once(self):
        from irinbench.corpus import CorpusError

        with self.assertRaises(CorpusError) as ctx:
            self._corpus()(_FakeCorpus("tasks", ["a"]), {"x", "y"})

        # Reporting one at a time makes a wrong list a guessing game.
        self.assertIn("'x'", str(ctx.exception))
        self.assertIn("'y'", str(ctx.exception))


class _FakeSpec:
    def __init__(self, spec_id: str) -> None:
        self.id = spec_id


class _FakeCorpus:
    def __init__(self, name: str, ids) -> None:
        self.name = name
        self.specs = [_FakeSpec(i) for i in ids]


if __name__ == "__main__":
    unittest.main()
