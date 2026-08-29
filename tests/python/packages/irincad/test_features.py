"""Cylindrical feature recognition, against geometry built in the test.

Real solids rather than fixtures. The whole value of this module is that it
reads a B-rep correctly, so a test that fed it a hand-written dictionary would
prove nothing about the only thing it does.
"""

import math
import unittest
from pathlib import Path

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


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class BlendClassificationTests(unittest.TestCase):
    """A fillet is not a hole, and telling them apart needs two signals.

    Each signal alone is wrong on a real part in this repository. A flange's
    outer cylinder is tangent to its edge fillets and is plainly a boss. A keyed
    bore is interrupted by its keyway and is plainly a hole. A blend is both
    partial and tangent.
    """

    @staticmethod
    def _features(shape):
        bbox = shape.bounding_box()
        return features.features_of_shape(
            shape.wrapped,
            bbox=(bbox.min.X, bbox.min.Y, bbox.min.Z, bbox.max.X, bbox.max.Y, bbox.max.Z),
        )

    def test_a_concave_corner_fillet_is_not_counted_as_a_hole(self):
        # This is the defect the classifier exists to fix: an L-bracket's 2 mm
        # transition fillet was reported as a 4 mm hole, so the bracket looked
        # like it had five holes when it has four.
        from build123d import fillet as b_fillet

        with BuildPart() as part:
            Box(60.0, 40.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
            Box(60.0, 10.0, 40.0, align=(Align.CENTER, Align.MIN, Align.MIN))
        solid = part.part
        edges = [
            e for e in solid.edges()
            if abs(e.length - 60.0) < 1e-6
        ]
        solid = b_fillet(edges[:1], radius=2.0) if edges else solid

        found = self._features(solid)
        self.assertEqual([f for f in found if f.kind == features.KIND_HOLE], [])
        blends = [f for f in found if f.kind in features.BLEND_KINDS]
        self.assertTrue(blends, "the filleted edge should be recognised as a blend")
        self.assertAlmostEqual(blends[0].diameter / 2.0, 2.0, places=6)

    def test_a_full_cylinder_stays_a_hole_even_when_tangent(self):
        # A flange's outer cylinder is tangent to the fillets above and below it.
        # Tangency alone must not reclassify it.
        with BuildPart() as part:
            Cylinder(radius=20.0, height=10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations(Location((0.0, 0.0, -1.0))):
                Cylinder(radius=5.0, height=12.0,
                         align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
        found = self._features(part.part)
        kinds = {f.kind for f in found}
        self.assertIn(features.KIND_HOLE, kinds)
        self.assertIn(features.KIND_BOSS, kinds)
        self.assertNotIn(features.KIND_FILLET, kinds)

    def test_a_partial_cylinder_with_no_tangency_stays_a_hole(self):
        # A keyed bore spans less than a full turn and is still a bore, because
        # it meets its keyway walls at sharp edges.
        with BuildPart() as part:
            Cylinder(radius=20.0, height=20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
            with Locations(Location((0.0, 0.0, -1.0))):
                Cylinder(radius=8.0, height=22.0,
                         align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
            with Locations(Location((0.0, 8.0, -1.0))):
                Box(4.0, 4.0, 22.0, align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.SUBTRACT)
        found = self._features(part.part)
        bores = [f for f in found if f.kind == features.KIND_HOLE and abs(f.diameter - 16.0) < 0.01]
        self.assertEqual(len(bores), 1, "a keyed bore is a hole, not a blend")
        self.assertFalse(bores[0].complete, "and it is genuinely partial")

    def test_blends_never_form_a_hole_pattern(self):
        # Four fillets on parallel corners would otherwise fit a circle and be
        # announced as a bolt pattern.
        blend = features.CylindricalFeature(
            ref="o1", name="p", kind=features.KIND_FILLET, diameter=4.0,
            axis=(0.0, 0.0, 1.0), position=(10.0, 0.0, 0.0), depth=30.0,
            through=False, complete=False, face_count=1,
        )
        others = [
            features.CylindricalFeature(
                ref="o1", name="p", kind=features.KIND_FILLET, diameter=4.0,
                axis=(0.0, 0.0, 1.0), position=pos, depth=30.0,
                through=False, complete=False, face_count=1,
            )
            for pos in ((-10.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, -10.0, 0.0))
        ]
        self.assertEqual(features.hole_patterns([blend, *others]), [])


@unittest.skipUnless(HAVE_CAD, "build123d is not installed")
class DiscoveryResilienceTests(unittest.TestCase):
    """One malformed generator must not take its siblings down with it.

    Found by a benchmark submission. A directory of otherwise valid models plus
    one file whose gen_step() returned from inside a `with` block reported every
    model as broken, each carrying the malformed file's error. The guard in
    `_iter_python_sources` existed and caught only CadSourceError, while the
    metadata parser raises bare ValueError, so the guard never fired.

    The numbers that produced looked like a model that could do nothing.
    """

    def test_looking_up_one_target_survives_a_malformed_sibling(self):
        """Lookup is resilient; enumeration is not, and both are right.

        `iter_cad_sources` answers "what is in this tree", and a malformed
        generator is part of that answer, so it raises and the author sees it.
        A lookup answers "where is THIS target", and a different file being
        broken is not an answer to that question.
        """
        import tempfile
        from irincad import catalog

        good = (
            "from build123d import Align, Box, BuildPart\n\n"
            "def gen_step():\n"
            "    with BuildPart() as part:\n"
            "        Box(40.0, 25.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
            "    return part.part\n"
        )
        # Valid Python, and the natural way to write it, but the metadata parser
        # only inspects top-level statements so this return is invisible to it.
        malformed = good.replace("    return part.part", "        return part.part")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.step.py").write_text(good, encoding="utf-8")
            (root / "bad.step.py").write_text(malformed, encoding="utf-8")

            found = catalog.find_source_by_path(root / "good.step.py", root)
            self.assertIsNotNone(
                found, "the valid generator was hidden by its malformed sibling"
            )
            self.assertEqual(Path(found.script_path).name, "good.step.py")

            # Enumeration stays strict: the author is told the tree is broken.
            with self.assertRaises((ValueError, catalog.CadSourceError)):
                catalog.iter_cad_sources(root)

    def test_a_sibling_that_will_not_even_parse_is_survivable_too(self):
        """The second poisoning bug, shipped by naming exception types.

        The first fix caught CadSourceError and ValueError. A file that is not
        valid Python raises RuntimeError from the parser, escaped both, and
        poisoned every lookup in the directory exactly as before. A model that
        leaked its chain of thought instead of code produced one, and one was
        enough to report all twenty-eight tasks as broken.

        The guard now catches everything, because the failure modes of reading
        arbitrary third-party files are open-ended and two attempts at naming
        them both missed one.
        """
        import tempfile

        from irincad import catalog

        good = "\n".join(
            [
                "from build123d import Align, Box, BuildPart",
                "",
                "def gen_step():",
                "    with BuildPart() as part:",
                "        Box(40.0, 25.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                "    return part.part",
                "",
            ]
        )
        prose = "We need to think. Let's assume the base is 10 mm, and it isn't code.\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.step.py").write_text(good, encoding="utf-8")
            (root / "prose.step.py").write_text(prose, encoding="utf-8")

            found = catalog.find_source_by_path(root / "good.step.py", root)

        self.assertIsNotNone(found, "an unparseable sibling hid a valid generator")
