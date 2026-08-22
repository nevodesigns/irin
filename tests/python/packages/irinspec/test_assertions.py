import unittest

from irinspec import (
    BoltCircle,
    BossCount,
    Bounds,
    FeatureSpacing,
    FilletCount,
    Volume,
    ClashCount,
    Distance,
    EdgeCount,
    FaceCount,
    HoleCount,
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
            assertion_from_dict({"kind": "fillet_radius", "value": 2.0}, "assertions[0]")
        message = str(ctx.exception)
        self.assertIn("fillet_radius", message)
        self.assertIn("valid_solid", message)
        # The reason matters: a silently accepted kind is a false green.
        self.assertIn("appears to check something nothing measures", message)

    def test_kinds_exist_exactly_when_their_measurement_does(self):
        # hole_count and bolt_circle were on the absent list until
        # irincad.features could recognise cylindrical features. They are here
        # now because that measurement is, and for no other reason.
        for measurable in ("hole_count", "bolt_circle"):
            self.assertIn(measurable, SUPPORTED_KINDS)

        # fillet_count joined when edge tangency could tell a blend from an
        # opening, which also stopped fillets being counted as holes.
        self.assertIn("fillet_count", SUPPORTED_KINDS)

        # Still absent, and still for the original reason: nothing measures them.
        for unmeasurable in ("chamfer_size", "wall_thickness", "draft_angle"):
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


class HoleCountTests(unittest.TestCase):
    def test_the_common_engineering_sentence_round_trips(self):
        # "four 8 mm through-holes", which is what most prompts are made of.
        assertion = HoleCount(value=4, diameter=8.0, through=True)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "exactly 4 holes of 8 mm, through")

    def test_a_bare_count_needs_no_diameter(self):
        assertion = HoleCount(value=6)
        self.assertEqual(assertion.to_dict(), {"kind": "hole_count", "value": 6})
        self.assertEqual(assertion.describe(), "exactly 6 holes")

    def test_blind_and_through_are_distinguishable(self):
        self.assertIn("blind", HoleCount(value=2, through=False).describe())
        self.assertIn("through", HoleCount(value=2, through=True).describe())

    def test_a_non_positive_diameter_is_refused(self):
        with self.assertRaises(SpecError):
            HoleCount(value=1, diameter=0.0)

    def test_value_is_required(self):
        with self.assertRaises(SpecError) as ctx:
            assertion_from_dict({"kind": "hole_count", "diameter": 8.0}, "a[0]")
        self.assertIn("a[0].value", str(ctx.exception))


class BossCountTests(unittest.TestCase):
    def test_a_round_part_states_its_outer_diameter_exactly(self):
        # The reason this kind exists: a bbox is read from tessellated topology
        # and reports an 80 mm flange as 79.95, so `size` cannot state a round
        # dimension without a tolerance loose enough to accept a wrong one.
        assertion = BossCount(value=1, diameter=80.0)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "exactly 1 external cylinder of 80 mm")

    def test_more_than_one_cylinder_pluralizes(self):
        self.assertIn("2 external cylinders", BossCount(value=2, diameter=70.0).describe())

    def test_a_non_positive_diameter_is_refused(self):
        with self.assertRaises(SpecError):
            BossCount(value=1, diameter=-5.0)


class BoltCircleTests(unittest.TestCase):
    def test_the_canonical_flange_requirement_round_trips(self):
        assertion = BoltCircle(diameter=60.0, count=6, hole_diameter=6.6)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "6 holes on a 60 mm bolt circle, each 6.6 mm")

    def test_fewer_than_three_holes_cannot_establish_a_circle(self):
        # Any two points lie on infinitely many circles, so a pair cannot
        # establish a pitch circle no matter how precisely it is measured.
        with self.assertRaises(SpecError) as ctx:
            BoltCircle(diameter=60.0, count=2)
        self.assertIn("infinitely many circles", str(ctx.exception))

    def test_a_non_positive_pitch_circle_is_refused(self):
        with self.assertRaises(SpecError):
            BoltCircle(diameter=0.0, count=4)

    def test_diameter_and_count_are_both_required(self):
        for payload in (
            {"kind": "bolt_circle", "count": 4},
            {"kind": "bolt_circle", "diameter": 60.0},
        ):
            with self.assertRaises(SpecError):
                assertion_from_dict(payload, "a[0]")


if __name__ == "__main__":
    unittest.main()


class FeatureSpacingTests(unittest.TestCase):
    def test_the_dimension_an_assembly_is_specified_by(self):
        # A shock absorber is sold by its eye-to-eye length.
        assertion = FeatureSpacing(diameter=12.0, value=340.0)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "the two 12 mm bores are 340 mm apart")

    def test_bosses_can_be_measured_between_too(self):
        assertion = FeatureSpacing(diameter=20.0, value=60.0, feature="boss")
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertIn("external cylinders", assertion.describe())

    def test_a_non_positive_dimension_is_refused(self):
        with self.assertRaises(SpecError):
            FeatureSpacing(diameter=12.0, value=0.0)
        with self.assertRaises(SpecError):
            FeatureSpacing(diameter=0.0, value=340.0)

    def test_an_unknown_feature_kind_is_refused(self):
        with self.assertRaises(SpecError):
            FeatureSpacing(diameter=12.0, value=340.0, feature="slot")

    def test_diameter_and_value_are_both_required(self):
        for payload in (
            {"kind": "feature_spacing", "diameter": 12.0},
            {"kind": "feature_spacing", "value": 340.0},
        ):
            with self.assertRaises(SpecError):
                assertion_from_dict(payload, "a[0]")


class FilletCountTests(unittest.TestCase):
    def test_a_fillet_is_specified_by_radius(self):
        # Every drawing calls out "a 2 mm fillet", never "a 4 mm fillet".
        assertion = FilletCount(value=1, radius=2.0)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "exactly 1 blended edge of radius 2 mm")

    def test_concave_and_convex_can_be_distinguished_when_it_matters(self):
        self.assertIn("fillet", FilletCount(value=1, convex=False).describe())
        self.assertIn("round", FilletCount(value=1, convex=True).describe())

    def test_both_are_counted_by_default(self):
        # Most requirements say "fillet" for either.
        self.assertIsNone(FilletCount(value=2).convex)
        self.assertIn("blended edges", FilletCount(value=2).describe())

    def test_a_non_positive_radius_is_refused(self):
        with self.assertRaises(SpecError):
            FilletCount(value=1, radius=0.0)

    def test_value_is_required(self):
        with self.assertRaises(SpecError):
            assertion_from_dict({"kind": "fillet_count", "radius": 2.0}, "a[0]")


class VolumeTests(unittest.TestCase):
    def test_volume_round_trips(self):
        assertion = Volume(value=192000.0)
        self.assertEqual(assertion_from_dict(assertion.to_dict(), "a[0]"), assertion)
        self.assertEqual(assertion.describe(), "192000 mm^3 of material")

    def test_the_default_tolerance_is_relative(self):
        # Volumes span orders of magnitude across a corpus, and a fixed band
        # that suits a washer is meaningless on a gearbox.
        assertion = Volume(value=1000.0)
        low, high = assertion.tolerance.bounds(1000.0)
        self.assertAlmostEqual(low, 990.0)
        self.assertAlmostEqual(high, 1010.0)

    def test_a_non_positive_volume_is_refused(self):
        with self.assertRaises(SpecError):
            Volume(value=0.0)

    def test_value_is_required(self):
        with self.assertRaises(SpecError):
            assertion_from_dict({"kind": "volume"}, "a[0]")
