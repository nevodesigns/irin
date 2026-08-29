"""Result records: what they keep, and what they must not keep.

Fast and kernel-free. These test the shape of a stored result, not geometry.
"""

from __future__ import annotations

import unittest


class StableDetailTests(unittest.TestCase):
    """A result file must diff against the next run of the same submission.

    OCP prints its objects with a memory address, so two identical runs produced
    result files that differed on every line carrying a kernel error. The scores
    matched; the bytes did not. A diff meant to show what changed about an answer
    was instead full of addresses.
    """

    def test_an_address_does_not_survive_into_a_stored_detail(self):
        from irineval.results import AssertionResult

        raw = (
            "SetRotation(): incompatible function arguments.\n"
            "Invoked with: <OCP.OCP.gp.gp_Trsf object at 0x7d9df072fbf0>, "
            "<OCP.OCP.gp.gp_Vec object at 0x7d9df07244b0>"
        )
        result = AssertionResult(
            kind="valid_solid", description="d", passed=False, detail=raw
        )

        self.assertNotIn("0x7d9df072fbf0", result.detail)
        self.assertIn("0x...", result.detail)
        # The information the reader needs is untouched.
        self.assertIn("SetRotation()", result.detail)
        self.assertIn("gp_Trsf", result.detail)

    def test_two_runs_that_differ_only_by_address_compare_equal(self):
        from irineval.results import AssertionResult

        def at(address: str) -> str:
            return AssertionResult(
                kind="valid_solid",
                description="d",
                passed=False,
                detail=f"boom <OCP.gp_Trsf object at {address}>",
            ).detail

        self.assertEqual(at("0x7d9df072fbf0"), at("0x709e097a8ab0"))

    def test_a_dimension_is_not_mistaken_for_an_address(self):
        from irineval.results import AssertionResult

        result = AssertionResult(
            kind="size", description="d", passed=False, detail="expected 0x40 mm slot"
        )
        # Too short to be an address, and a real number in a real message.
        self.assertEqual(result.detail, "expected 0x40 mm slot")


if __name__ == "__main__":
    unittest.main()
