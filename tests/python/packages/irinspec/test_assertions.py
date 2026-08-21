import unittest

from irinspec import (
    Bounds,
    Distance,
    EdgeCount,
    FaceCount,
    NoInterference,
    Size,
    PartCount,
    SOURCES,
    SUPPORTED_KINDS,
    SpecError,
    Tolerance,
    ValidSolid,
    assertion_from_dict,
)
from irinspec.assertions import REGISTRY


class RegistryTests(unittest.TestCase):
    def test_every_registered_kind_names_a_real_inspection_source(self):
        # The evaluator dispatches on `source`. A kind pointing at a source that
        # does not exist would parse cleanly and then never be checked.
        for kind, cls in REGISTRY.items():
            self.assertIn(cls.source, SOURCES, f"{kind} has an unknown source {cls.source!r}")

    def test_registry_key_matches_the_class_kind(self):
        for kind, cls in REGISTRY.items():
            self.assertEqual(kind, cls.kind)

    def test_an_unknown_kind_is_refused_and_lists_what_is_supported(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict({"kind": "hole_count", "value": 6}, "assertions[0]")
        message = str(ctx.exception)
        self.assertIn("hole_count", message)
        self.assertIn("valid_solid", message)
        # The reason matters: a silently accepted kind is a false green.
        self.assertIn("appears to check something nothing measures", message)

    def test_hole_and_feature_kinds_are_absent_until_they_can_be_measured(self):
        for unmeasurable in ("hole_count", "bolt_circle", "fillet_radius", "wall_thickness"):
            self.assertNotIn(unmeasurable, SUPPORTED_KINDS)


class ValidSolidTests(unittest.TestCase):
    def test_defaults_to_requiring_a_closed_solid(self):
        assertion = ValidSolid()
        self.assertFalse(assertion.allow_open)
        self.assertEqual(assertion.to_dict(), {"kind": "valid_solid"})

    def test_open_shells_can_be_declared_intentional(self):
        assertion = ValidSolid(allow_open=True)
        self.assertEqual(assertion.to_dict(), {"kind": "valid_solid", "allow_open": True})

    def test_allow_open_must_be_a_boolean(self):
        with self.assertRaises(SpecError):
            assertion_from_dict({"kind": "valid_solid", "allow_open": "yes"}, "a[0]")


class SizeTests(unittest.TestCase):
    def test_a_subset_of_axes_is_allowed(self):
        # A plate specified only by thickness should not have to invent x and y.
        assertion = Size(z=3.0)
        self.assertEqual(assertion.axes(), {"z": 3.0})

    def test_at_least_one_axis_is_required(self):
        with self.assertRaises(SpecError) as ctx:
            Size()
        self.assertIn("at least one of x, y, z", str(ctx.exception))

    def test_a_non_positive_extent_is_refused(self):
        with self.assertRaises(SpecError):
            Size(x=0.0)
        with self.assertRaises(SpecError):
            Size(x=-10.0)

    def test_round_trip(self):
        assertion = Size(x=100.0, y=60.0, z=20.0, tolerance=Tolerance.symmetric(0.2))
        rebuilt = assertion_from_dict(assertion.to_dict(), "a[0]")
        self.assertEqual(rebuilt, assertion)

    def test_a_bare_tolerance_number_parses(self):
        assertion = assertion_from_dict({"kind": "size", "x": 50.0, "tolerance": 0.5}, "a[0]")
        self.assertEqual(assertion.tolerance, Tolerance.symmetric(0.5))

    def test_describe_reads_as_a_sentence(self):
        self.assertEqual(Size(x=100.0, z=20.0).describe(), "bounding box x=100.0, z=20.0 (mm)")


class BoundsTests(unittest.TestCase):
    def test_bounds_catch_a_correct_part_at_the_wrong_origin(self):
        assertion = Bounds(min=(-50.0, -30.0, 0.0), max=(50.0, 30.0, 20.0))
        rebuilt = assertion_from_dict(assertion.to_dict(), "a[0]")
        self.assertEqual(rebuilt, assertion)

    def test_at_least_one_corner_is_required(self):
        with self.assertRaises(SpecError):
            Bounds()

    def test_a_corner_needs_three_numbers(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict({"kind": "bounds", "min": [0.0, 1.0]}, "a[0]")
        self.assertIn("three numbers", str(ctx.exception))


class CountTests(unittest.TestCase):
    def test_each_count_round_trips(self):
        for cls in (PartCount, FaceCount, EdgeCount):
            assertion = cls(value=14)
            self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)

    def test_value_is_required(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict({"kind": "part_count"}, "a[0]")
        self.assertIn("a[0].value", str(ctx.exception))

    def test_a_negative_count_is_refused(self):
        with self.assertRaises(SpecError):
            assertion_from_dict({"kind": "face_count", "value": -1}, "a[0]")

    def test_a_float_count_is_refused(self):
        with self.assertRaises(SpecError):
            assertion_from_dict({"kind": "edge_count", "value": 3.5}, "a[0]")

    def test_describe_pluralizes(self):
        self.assertEqual(PartCount(value=1).describe(), "exactly 1 part")
        self.assertEqual(PartCount(value=3).describe(), "exactly 3 parts")

    def test_solid_count_is_not_a_kind(self):
        # It was, briefly. The only available figure counts leaf occurrences,
        # which does not catch a failed boolean leaving two bodies in one part,
        # so the name was claiming more than the measurement could show.
        self.assertNotIn("solid_count", SUPPORTED_KINDS)
        self.assertIn("part_count", SUPPORTED_KINDS)


class NoInterferenceTests(unittest.TestCase):
    def test_a_volume_floor_separates_contact_from_a_clash(self):
        # Neighbouring panels share a face by design and the boolean returns
        # hairline slivers for those.
        assertion = NoInterference(volume_tolerance=25.0)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)

    def test_a_negative_floor_is_refused(self):
        with self.assertRaises(SpecError):
            NoInterference(volume_tolerance=-1.0)


class DistanceTests(unittest.TestCase):
    def test_round_trip(self):
        assertion = Distance(
            from_ref="#o1.1.f2",
            to_ref="#o1.2.f5",
            axis="z",
            value=12.5,
            tolerance=Tolerance.symmetric(0.05),
        )
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)

    def test_the_axis_is_required_rather_than_inferred(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict(
                {"kind": "distance", "from": "#a", "to": "#b", "value": 1.0}, "a[0]"
            )
        self.assertIn("ambiguous", str(ctx.exception))

    def test_an_unknown_axis_is_refused(self):
        with self.assertRaises(SpecError):
            Distance(from_ref="#a", to_ref="#b", axis="w", value=1.0)

    def test_refs_must_look_like_selector_refs(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict(
                {"kind": "distance", "from": "o1.1", "to": "#b", "axis": "x", "value": 1.0}, "a[0]"
            )
        self.assertIn("start with '#'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
