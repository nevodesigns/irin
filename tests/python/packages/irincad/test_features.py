"""Cylindrical feature recognition, against geometry built in the test.

Real solids rather than fixtures. The whole value of this module is that it
reads a B-rep correctly, so a test that fed it a hand-written dictionary would
prove nothing about the only thing it does.
"""

import math
import unittest

try:
    from build123d import Align, Box, BuildPart, Cylinder, Location, Locations, Mode

    HAVE_CAD = True
except Exception:  # pragma: no cover - environment probe
    HAVE_CAD = False

from irincad import features


class PureGeometryTests(unittest.TestCase):
    """The parts that need no CAD kernel."""

    def test_a_direction_and_its_opposite_describe_one_axis(self):
        # Two faces of one hole can report opposite directions. Without this
        # they would never group and every hole would be counted twice.
        self.assertEqual(
            features._canonical_direction((0.0, 0.0, 1.0)),
            features._canonical_direction((0.0, 0.0, -1.0)),
        )

    def test_the_axis_anchor_is_independent_of_where_on_the_line_you_start(self):
        direction = (0.0, 0.0, 1.0)
        a = features._point_on_axis_nearest_origin((5.0, 3.0, -100.0), direction)
        b = features._point_on_axis_nearest_origin((5.0, 3.0, 250.0), direction)
        self.assertEqual([round(v, 9) for v in a], [round(v, 9) for v in b])
        self.assertEqual([round(v, 6) for v in a], [5.0, 3.0, 0.0])

    def test_a_bbox_span_projects_onto_a_direction(self):
        bbox = (-10.0, -5.0, 0.0, 10.0, 5.0, 20.0)
        self.assertEqual(features._bbox_span_along(bbox, (0.0, 0.0, 1.0)), (0.0, 20.0))
        self.assertEqual(features._bbox_span_along(bbox, (1.0, 0.0, 0.0)), (-10.0, 10.0))


def _feature(diameter, position, axis=(0.0, 0.0, 1.0)):
    return features.CylindricalFeature(
        ref="o1",
        name="part",
        kind=features.KIND_HOLE,
        diameter=diameter,
        axis=axis,
        position=position,
        depth=10.0,
        through=True,
        complete=True,
        face_count=1,
    )


class PatternTests(unittest.TestCase):
    def test_evenly_spaced_holes_are_a_bolt_circle(self):
        radius = 30.0
        holes = [
            _feature(6.6, (radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a)), 0.0))
            for a in (0, 60, 120, 180, 240, 300)
        ]
        pattern = features.hole_patterns(holes)[0]
        self.assertEqual(pattern.count, 6)
        self.assertAlmostEqual(pattern.circle_diameter, 60.0, places=6)
        self.assertTrue(pattern.uniform)

    def test_a_rectangular_pattern_fits_a_circle_and_is_not_uniform(self):
        # The trap this module exists to avoid. Four corners of a rectangle are
        # equidistant from its centre, so a circle fits them perfectly.
        holes = [
            _feature(8.0, (x, y, 0.0))
            for x, y in ((-35.0, -20.0), (-35.0, 20.0), (35.0, -20.0), (35.0, 20.0))
        ]
        pattern = features.hole_patterns(holes)[0]
        self.assertEqual(pattern.count, 4)
        self.assertAlmostEqual(pattern.max_radius_deviation, 0.0, places=9)
        self.assertFalse(pattern.uniform, "a rectangle is not a bolt circle")

    def test_two_holes_are_not_a_pattern(self):
        # Any two points lie on infinitely many circles, so a fit would be
        # meaningless rather than merely imprecise.
        holes = [_feature(5.0, (-10.0, 0.0, 0.0)), _feature(5.0, (10.0, 0.0, 0.0))]
        self.assertEqual(features.hole_patterns(holes), [])

    def test_different_diameters_are_different_patterns(self):
        holes = [_feature(6.0, (10.0, 0.0, 0.0)), _feature(6.0, (-10.0, 0.0, 0.0)),
                 _feature(6.0, (0.0, 10.0, 0.0)), _feature(6.0, (0.0, -10.0, 0.0)),
                 _feature(3.0, (5.0, 0.0, 0.0)), _feature(3.0, (-5.0, 0.0, 0.0)),
                 _feature(3.0, (0.0, 5.0, 0.0)), _feature(3.0, (0.0, -5.0, 0.0))]
        patterns = features.hole_patterns(holes)
        self.assertEqual(len(patterns), 2)
        self.assertEqual({round(p.circle_diameter, 3) for p in patterns}, {20.0, 10.0})


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class RecognitionTests(unittest.TestCase):
    """Against solids built here, so the expected answer is known exactly."""

    @staticmethod
    def _plate_with_holes(length=100.0, width=60.0, height=20.0, hole_d=8.0, positions=None, blind=False):
        positions = positions or [(-35.0, -20.0), (-35.0, 20.0), (35.0, -20.0), (35.0, 20.0)]
        depth = height / 2.0 if blind else height + 2.0
        z0 = height - depth if blind else -1.0
        with BuildPart() as part:
            Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
            for x, y in positions:
                with Locations(Location((x, y, z0))):
                    Cylinder(
                        radius=hole_d / 2.0,
                        height=depth,
                        align=(Align.CENTER, Align.CENTER, Align.MIN),
                        mode=Mode.SUBTRACT,
                    )
        return part.part

    def _features(self, shape):
        bbox = shape.bounding_box()
        return features.features_of_shape(
            shape.wrapped,
            ref="o1",
            name="test",
            bbox=(bbox.min.X, bbox.min.Y, bbox.min.Z, bbox.max.X, bbox.max.Y, bbox.max.Z),
        )

    def test_four_through_holes_are_found_with_their_real_diameter(self):
        found = self._features(self._plate_with_holes())
        holes = [f for f in found if f.kind == features.KIND_HOLE]
        self.assertEqual(len(holes), 4)
        for hole in holes:
            self.assertAlmostEqual(hole.diameter, 8.0, places=6)
            self.assertTrue(hole.through)
            self.assertTrue(hole.complete)
            self.assertEqual([round(v, 6) for v in hole.axis], [0.0, 0.0, 1.0])

    def test_hole_positions_match_where_they_were_cut(self):
        holes = [f for f in self._features(self._plate_with_holes()) if f.kind == features.KIND_HOLE]
        found = sorted((round(h.position[0], 3), round(h.position[1], 3)) for h in holes)
        self.assertEqual(found, [(-35.0, -20.0), (-35.0, 20.0), (35.0, -20.0), (35.0, 20.0)])

    def test_a_blind_hole_is_not_reported_as_through(self):
        holes = [
            f for f in self._features(self._plate_with_holes(blind=True))
            if f.kind == features.KIND_HOLE
        ]
        self.assertEqual(len(holes), 4)
        self.assertTrue(all(not hole.through for hole in holes))

    def test_an_external_cylinder_is_a_boss_not_a_hole(self):
        # The discriminator is face orientation, and this is the case that
        # proves it: the same solid holds one of each.
        with BuildPart() as part:
            Cylinder(radius=27.0, height=20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations(Location((0.0, 0.0, -1.0))):
                Cylinder(
                    radius=10.0,
                    height=22.0,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.SUBTRACT,
                )
        found = self._features(part.part)
        kinds = {f.kind: f for f in found}
        self.assertIn(features.KIND_BOSS, kinds)
        self.assertIn(features.KIND_HOLE, kinds)
        self.assertAlmostEqual(kinds[features.KIND_BOSS].diameter, 54.0, places=6)
        self.assertAlmostEqual(kinds[features.KIND_HOLE].diameter, 20.0, places=6)

    def test_a_real_bolt_circle_is_recognised_as_uniform(self):
        radius = 30.0
        positions = [
            (radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a)))
            for a in (0, 60, 120, 180, 240, 300)
        ]
        found = self._features(
            self._plate_with_holes(length=100.0, width=100.0, hole_d=6.6, positions=positions)
        )
        pattern = features.hole_patterns(found)[0]
        self.assertEqual(pattern.count, 6)
        self.assertAlmostEqual(pattern.circle_diameter, 60.0, places=4)
        self.assertTrue(pattern.uniform)
        self.assertAlmostEqual(pattern.diameter, 6.6, places=6)

    def test_a_solid_with_no_cylinders_reports_nothing(self):
        with BuildPart() as part:
            Box(10.0, 10.0, 10.0)
        self.assertEqual(self._features(part.part), [])


if __name__ == "__main__":
    unittest.main()
