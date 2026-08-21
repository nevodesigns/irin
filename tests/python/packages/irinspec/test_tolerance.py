import unittest

from irinspec import SpecError, Tolerance


class ToleranceBandTests(unittest.TestCase):
    def test_symmetric_band_is_centred_on_nominal(self):
        tol = Tolerance.symmetric(0.2)
        self.assertEqual(tol.bounds(80.0), (79.8, 80.2))
        self.assertTrue(tol.contains(80.0, 79.85))
        self.assertTrue(tol.contains(80.0, 80.2))
        self.assertFalse(tol.contains(80.0, 80.25))

    def test_asymmetric_band_is_not_centred(self):
        # +0.1 / -0.05: a clearance hole may run oversize but not undersize.
        tol = Tolerance.asymmetric(0.1, 0.05)
        low, high = tol.bounds(10.0)
        self.assertAlmostEqual(low, 9.95)
        self.assertAlmostEqual(high, 10.1)
        self.assertTrue(tol.contains(10.0, 10.08))
        self.assertFalse(tol.contains(10.0, 9.9))

    def test_relative_band_scales_with_nominal(self):
        tol = Tolerance.relative_fraction(0.01)
        self.assertEqual(tol.bounds(100.0), (99.0, 101.0))
        self.assertEqual(tol.bounds(1000.0), (990.0, 1010.0))

    def test_relative_band_widens_symmetrically_for_a_negative_nominal(self):
        # Taken against abs(nominal), so a coordinate below the origin widens the
        # band the same way a positive one does instead of inverting it.
        tol = Tolerance.relative_fraction(0.1)
        low, high = tol.bounds(-50.0)
        self.assertEqual((low, high), (-55.0, -45.0))
        self.assertLess(low, high)

    def test_absolute_and_relative_parts_add(self):
        tol = Tolerance(plus=0.5, minus=0.5, relative=0.01)
        self.assertEqual(tol.bounds(100.0), (98.5, 101.5))


class ToleranceReportingTests(unittest.TestCase):
    def test_deviation_keeps_its_sign(self):
        tol = Tolerance.symmetric(0.2)
        self.assertAlmostEqual(tol.deviation(80.0, 80.3), 0.3)
        self.assertAlmostEqual(tol.deviation(80.0, 79.7), -0.3)

    def test_excess_is_zero_inside_the_band(self):
        # The deviation alone does not say whether it mattered. 0.15 inside a
        # 0.2 band is a pass, and reporting it as an error would be noise.
        tol = Tolerance.symmetric(0.2)
        self.assertEqual(tol.excess(80.0, 80.15), 0.0)

    def test_excess_measures_past_the_band_not_past_nominal(self):
        tol = Tolerance.symmetric(0.2)
        self.assertAlmostEqual(tol.excess(80.0, 80.5), 0.3)
        self.assertAlmostEqual(tol.excess(80.0, 79.5), -0.3)


class ToleranceValidationTests(unittest.TestCase):
    def test_a_zero_band_is_refused(self):
        # An exact float comparison rejects geometry that is correct, so it is
        # refused at construction rather than failing mysteriously on a model.
        with self.assertRaises(SpecError) as ctx:
            Tolerance()
        self.assertIn("exact float comparison", str(ctx.exception))

    def test_a_negative_magnitude_is_refused_with_the_convention_explained(self):
        with self.assertRaises(SpecError) as ctx:
            Tolerance(plus=0.1, minus=-0.05)
        self.assertIn("positive 'minus'", str(ctx.exception))

    def test_a_boolean_is_not_a_number(self):
        with self.assertRaises(SpecError):
            Tolerance(plus=True)


class ToleranceParsingTests(unittest.TestCase):
    def test_a_bare_number_reads_as_symmetric(self):
        self.assertEqual(Tolerance.from_value(0.2), Tolerance.symmetric(0.2))

    def test_each_mapping_form_parses(self):
        self.assertEqual(Tolerance.from_value({"symmetric": 0.2}), Tolerance.symmetric(0.2))
        self.assertEqual(
            Tolerance.from_value({"plus": 0.1, "minus": 0.05}), Tolerance.asymmetric(0.1, 0.05)
        )
        self.assertEqual(
            Tolerance.from_value({"relative": 0.01}), Tolerance.relative_fraction(0.01)
        )

    def test_symmetric_combined_with_plus_is_refused_as_contradictory(self):
        with self.assertRaises(SpecError) as ctx:
            Tolerance.from_value({"symmetric": 0.2, "plus": 0.4})
        self.assertIn("same two bounds", str(ctx.exception))

    def test_a_misspelled_key_is_refused_rather_than_ignored(self):
        with self.assertRaises(SpecError) as ctx:
            Tolerance.from_value({"symetric": 0.2}, path="assertions[0].tolerance")
        message = str(ctx.exception)
        self.assertIn("assertions[0].tolerance", message)
        self.assertIn("symetric", message)

    def test_a_boolean_is_refused_before_it_becomes_one_point_zero(self):
        with self.assertRaises(SpecError):
            Tolerance.from_value(True)

    def test_round_trip_through_the_shortest_form(self):
        for tol in (
            Tolerance.symmetric(0.2),
            Tolerance.asymmetric(0.1, 0.05),
            Tolerance.relative_fraction(0.01),
            Tolerance(plus=0.5, minus=0.25, relative=0.01),
        ):
            self.assertEqual(Tolerance.from_value(tol.to_dict()), tol)


if __name__ == "__main__":
    unittest.main()
