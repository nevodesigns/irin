"""Auditing a stored result for the shape of a harness fault.

The cases here are the actual bad results this repository produced, and the
actual good ones it produced beside them. A check that fires on both is worse
than no check, because a warning that cries wolf teaches the reader to skip it.
"""

from __future__ import annotations

import unittest

from irinbench.audit import audit_result


def assertion(passed: bool, detail: str = "") -> dict:
    return {"kind": "valid_solid", "passed": passed, "detail": detail}


def spec(name: str, *details: str, ok: bool = False) -> dict:
    return {
        "spec": name,
        "ok": ok,
        "assertions": [assertion(False, d) for d in details],
    }


def result(specs: list, *, held: int = 28, partial: bool = False) -> dict:
    return {
        "corpus": {"name": "tasks", "kind": "task", "tasks": held},
        "partial": partial,
        "results": specs,
    }


def codes(data: dict) -> set:
    return {f.code for f in audit_result(data)}


class PoisoningTests(unittest.TestCase):
    """One fault reported as every fault.

    The real one: a single unreadable file aborted the directory walk, so all
    149 assertions in a submission came back carrying that one file's error.
    Two published results were scored that way, and one of them landed on the
    number it would have got anyway.
    """

    def test_one_reason_everywhere_is_caught(self):
        same = "Failed to parse clevis-bracket.step.py"
        data = result([spec(f"task{i}", *([same] * 5)) for i in range(28)])
        self.assertIn("uniform-failure-reason", codes(data))

    def test_the_finding_names_the_reason_so_it_can_be_checked(self):
        same = "Failed to parse clevis-bracket.step.py"
        data = result([spec(f"task{i}", *([same] * 5)) for i in range(28)])
        finding = next(f for f in audit_result(data) if f.code == "uniform-failure-reason")
        self.assertIn("clevis-bracket", finding.detail)
        self.assertTrue(finding.confirm)

    def test_a_genuinely_varied_failure_is_left_alone(self):
        # gpt-oss-120b: real API mistakes, all different. Must not fire.
        reasons = [
            "Cylinder.__init__() got an unexpected keyword argument 'diameter'",
            "'Location' object has no attribute 'rotate'",
            "'Vector' object has no attribute 'z'",
            "RectangleRounded.__init__() got an unexpected keyword argument",
            "expected 7, found 1",
            "z: 0 is outside [29.9, 30.1] by -29.9 mm",
        ]
        data = result([spec(f"task{i}", reasons[i % len(reasons)]) for i in range(28)])
        self.assertNotIn("uniform-failure-reason", codes(data))

    def test_a_small_run_is_not_judged(self):
        # Three failures agreeing is a small model being consistent, not a bug.
        data = result([spec("a", "boom"), spec("b", "boom")], held=2)
        self.assertEqual(codes(data), set())


class DiversityTests(unittest.TestCase):
    """Several harness faults rather than one.

    Spread across a few reasons, this stays under the uniformity threshold and
    still measures almost nothing.
    """

    def test_too_few_reasons_for_the_number_of_failures(self):
        data = result(
            [spec(f"task{i}", "ref not found for a", "ref not found for b") for i in range(28)]
        )
        self.assertIn("few-distinct-reasons", codes(data))

    def test_a_run_where_everything_passed_is_not_judged(self):
        data = result([{"spec": f"t{i}", "ok": True, "assertions": []} for i in range(28)])
        self.assertEqual(codes(data), set())


class PartialTests(unittest.TestCase):
    """A subset scored as if it were the whole corpus.

    The real one: a free tier refused six of twenty-eight requests, and the
    sweep scored the result as a full run. It read 4/28 and 14.3%, publishing a
    rate limiter as a modelling weakness.
    """

    def test_fewer_specs_than_the_corpus_without_the_flag(self):
        reasons = ["a", "b", "c", "d", "e", "f", "g"]
        data = result(
            [spec(f"task{i}", reasons[i % 7]) for i in range(22)], held=28, partial=False
        )
        self.assertIn("unmarked-partial", codes(data))

    def test_a_properly_marked_partial_is_fine(self):
        reasons = ["a", "b", "c", "d", "e", "f", "g"]
        data = result(
            [spec(f"task{i}", reasons[i % 7]) for i in range(22)], held=28, partial=True
        )
        self.assertNotIn("unmarked-partial", codes(data))

    def test_a_full_run_is_fine(self):
        reasons = ["a", "b", "c", "d", "e", "f", "g"]
        data = result([spec(f"task{i}", reasons[i % 7]) for i in range(28)], held=28)
        self.assertNotIn("unmarked-partial", codes(data))


class EmptyTests(unittest.TestCase):
    def test_a_result_with_no_specs_cannot_be_checked_and_says_so(self):
        self.assertIn("empty", codes(result([])))


class ThinSampleTests(unittest.TestCase):
    """Partial says incomplete. It does not say uninformative.

    The real one: a token-metered free tier let five of twenty-eight tasks
    through. The result printed an honest "0 / 5, 0.0%", which reads and quotes
    exactly like a measurement.
    """

    def _run(self, scored: int, held: int = 28) -> dict:
        reasons = ["a", "b", "c", "d", "e", "f", "g"]
        return result(
            [spec(f"task{i}", reasons[i % 7]) for i in range(scored)],
            held=held,
            partial=scored < held,
        )

    def test_a_fifth_of_the_corpus_is_flagged(self):
        self.assertIn("thin-sample", codes(self._run(5)))

    def test_being_correctly_marked_partial_does_not_excuse_it(self):
        # The two findings answer different questions, so honesty about the
        # denominator must not silence the point that the number cannot be used.
        data = self._run(5)
        self.assertTrue(data["partial"])
        self.assertIn("thin-sample", codes(data))

    def test_a_substantial_partial_is_left_alone(self):
        # 23 of 28 is worth reading, and saying otherwise would make the check
        # noise on the ordinary case of a run that lost a few tasks.
        self.assertNotIn("thin-sample", codes(self._run(23)))

    def test_a_full_run_is_left_alone(self):
        self.assertNotIn("thin-sample", codes(self._run(28)))

    def test_the_finding_gives_the_coverage_and_what_to_do(self):
        finding = next(f for f in audit_result(self._run(5)) if f.code == "thin-sample")
        self.assertIn("5 of 28", finding.detail)
        # The bias matters as much as the size, and the wording must say so.
        self.assertIn("survived", finding.detail)
        self.assertIn("re-score", finding.confirm)


if __name__ == "__main__":
    unittest.main()
