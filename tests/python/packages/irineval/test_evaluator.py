import unittest

import fixtures
from irinspec import (
    BoltCircle,
    BossCount,
    Bounds,
    FeatureSpacing,
    ClashCount,
    HoleCount,
    Distance,
    EdgeCount,
    FaceCount,
    NoInterference,
    PartCount,
    Size,
    Spec,
    Tolerance,
    ValidSolid,
)
from irineval import (
    FailureCode,
    RecordedRunner,
    evaluate,
    inspect_argv,
    plan,
    responses_from_pairs,
)

BLOCK = fixtures.BLOCK
GEARS = fixtures.GEARS


def block_runner(overrides: dict | None = None) -> RecordedRunner:
    """A runner answering every inspection the block fixtures cover.

    Overrides are passed as a dict rather than keyword arguments because the
    keys are argv tuples, and Python only allows string keywords.
    """
    table = {
        ("validate", BLOCK): fixtures.BLOCK_VALIDATE,
        ("refs", BLOCK, "--facts"): fixtures.BLOCK_FACTS,
        ("interfere", BLOCK, "--tolerance", "1"): fixtures.BLOCK_INTERFERE,
        ("measure", BLOCK, "--from", "#f4", "--to", "#f8", "--axis", "z"): fixtures.BLOCK_MEASURE_Z,
    }
    table.update(overrides or {})
    return RecordedRunner(responses_from_pairs(table.items()))


def spec_with(*assertions, spec_id="block") -> Spec:
    return Spec(id=spec_id, prompt="a 100 x 60 x 20 mm block", assertions=assertions)


class PlanningTests(unittest.TestCase):
    def test_every_facts_assertion_collapses_to_one_inspection(self):
        # Five claims, one refs --facts call. This is the whole reason a
        # spec-sized evaluation is affordable.
        spec = spec_with(
            Size(x=100.0),
            Bounds(max=(50.0, 30.0, 20.0)),
            PartCount(value=1),
            FaceCount(value=14),
            EdgeCount(value=32),
        )
        self.assertEqual(plan(spec, BLOCK), (("refs", BLOCK, "--facts"),))

    def test_different_interference_floors_are_different_questions(self):
        spec = spec_with(NoInterference(volume_tolerance=1.0), NoInterference(volume_tolerance=25.0))
        self.assertEqual(len(plan(spec, BLOCK)), 2)

    def test_allow_open_changes_the_validate_call(self):
        self.assertEqual(inspect_argv(ValidSolid(), BLOCK), ("validate", BLOCK))
        self.assertEqual(
            inspect_argv(ValidSolid(allow_open=True), BLOCK), ("validate", BLOCK, "--allow-open")
        )

    def test_a_whole_volume_floor_has_no_trailing_decimal_in_argv(self):
        argv = inspect_argv(NoInterference(volume_tolerance=25.0), BLOCK)
        self.assertEqual(argv[-1], "25")

    def test_the_plan_preserves_first_use_order(self):
        spec = spec_with(NoInterference(), Size(x=100.0), ValidSolid())
        self.assertEqual([argv[0] for argv in plan(spec, BLOCK)], ["interfere", "refs", "validate"])

    def test_every_supported_kind_is_bound_to_an_inspection(self):
        # A kind irinspec accepts but nothing here maps would parse cleanly and
        # then never be checked.
        from irinspec.assertions import REGISTRY

        samples = {
            "valid_solid": ValidSolid(),
            "size": Size(x=1.0),
            "bounds": Bounds(min=(0.0, 0.0, 0.0)),
            "part_count": PartCount(value=1),
            "face_count": FaceCount(value=1),
            "edge_count": EdgeCount(value=1),
            "no_interference": NoInterference(),
            "clash_count": ClashCount(value=0),
            "hole_count": HoleCount(value=1),
            "boss_count": BossCount(value=1),
            "feature_spacing": FeatureSpacing(diameter=6.0, value=60.0),
            "bolt_circle": BoltCircle(diameter=60.0, count=6),
            "distance": Distance(from_ref="#a", to_ref="#b", axis="x", value=1.0),
        }
        self.assertEqual(set(samples), set(REGISTRY))
        for assertion in samples.values():
            self.assertTrue(inspect_argv(assertion, BLOCK))


class PassingEvaluationTests(unittest.TestCase):
    def test_a_correct_block_passes_every_assertion(self):
        spec = spec_with(
            ValidSolid(),
            Size(x=100.0, y=60.0, z=20.0, tolerance=Tolerance.symmetric(0.2)),
            Bounds(min=(-50.0, -30.0, 0.0), max=(50.0, 30.0, 20.0)),
            PartCount(value=1),
            FaceCount(value=14),
            EdgeCount(value=32),
            NoInterference(),
            Distance(from_ref="#f4", to_ref="#f8", axis="z", value=20.0),
        )
        result = evaluate(spec, BLOCK, block_runner())
        self.assertTrue(result.ok, result.failures())
        self.assertEqual(result.passed_count, 8)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.undetermined_count, 0)

    def test_facts_are_fetched_once_however_many_assertions_use_them(self):
        runner = block_runner()
        spec = spec_with(Size(x=100.0), PartCount(value=1), FaceCount(value=14))
        evaluate(spec, BLOCK, runner)
        self.assertEqual(runner.call_count("refs"), 1)

    def test_a_subset_of_axes_ignores_the_others(self):
        # Asserting only thickness must not fail because x and y went unstated.
        spec = spec_with(Size(z=20.0))
        self.assertTrue(evaluate(spec, BLOCK, block_runner()).ok)


class FailingEvaluationTests(unittest.TestCase):
    def test_an_out_of_tolerance_extent_reports_which_axis_and_by_how_much(self):
        spec = spec_with(Size(x=100.0, y=61.0, z=20.0, tolerance=Tolerance.symmetric(0.2)))
        result = evaluate(spec, BLOCK, block_runner())
        self.assertFalse(result.ok)
        failure = result.failures()[0]
        self.assertEqual(failure.code, FailureCode.DIMENSION_OUT_OF_TOLERANCE)
        self.assertIn("y", failure.detail)
        self.assertAlmostEqual(failure.excess, -0.8)
        self.assertEqual(failure.actual, {"x": 100.0, "y": 60.0, "z": 20.0})

    def test_the_worst_axis_is_the_one_reported(self):
        spec = spec_with(Size(x=100.3, y=62.0, tolerance=Tolerance.symmetric(0.1)))
        failure = evaluate(spec, BLOCK, block_runner()).failures()[0]
        # y misses by 1.9, x by 0.2. The bigger miss is the one to chase.
        self.assertAlmostEqual(failure.excess, -1.9)

    def test_a_count_mismatch_is_its_own_code(self):
        spec = spec_with(PartCount(value=3))
        failure = evaluate(spec, BLOCK, block_runner()).failures()[0]
        self.assertEqual(failure.code, FailureCode.COUNT_MISMATCH)
        self.assertEqual(failure.detail, "expected 3, found 1")
        self.assertEqual(failure.deviation, -2.0)

    def test_an_inverted_solid_is_caught_and_names_the_reason(self):
        runner = block_runner({("validate", BLOCK): fixtures.INVERTED_SOLID_VALIDATE})
        failure = evaluate(spec_with(ValidSolid()), BLOCK, runner).failures()[0]
        self.assertEqual(failure.code, FailureCode.GEOMETRY_INVALID)
        self.assertIn("lid", failure.detail)
        self.assertIn("nonPositiveVolume", failure.detail)

    def test_a_defective_artifact_is_a_defect_not_a_broken_inspection(self):
        # validate and interfere both return ok:false with empty errors for a
        # genuinely bad artifact. Reading `ok` alone would report every real
        # defect as undetermined.
        runner = block_runner({("validate", BLOCK): fixtures.INVERTED_SOLID_VALIDATE})
        result = evaluate(spec_with(ValidSolid()), BLOCK, runner)
        self.assertEqual(result.defect_count, 1)
        self.assertEqual(result.undetermined_count, 0)

    def test_clashes_are_reported_with_the_parts_involved(self):
        runner = block_runner(
            {("interfere", BLOCK, "--tolerance", "1"): fixtures.CLASHING_INTERFERE}
        )
        failure = evaluate(spec_with(NoInterference()), BLOCK, runner).failures()[0]
        self.assertEqual(failure.code, FailureCode.INTERFERENCE)
        self.assertEqual(failure.actual, 2)
        self.assertIn("wheel_left into chassis", failure.detail)

    def test_a_wrong_origin_is_caught_by_bounds_though_size_passes(self):
        # The part is the right size and in the wrong place: the single most
        # common assembly defect, and invisible to a size check.
        spec = spec_with(
            Size(x=100.0, y=60.0, z=20.0),
            Bounds(min=(0.0, 0.0, 0.0)),
        )
        result = evaluate(spec, BLOCK, block_runner())
        self.assertFalse(result.ok)
        self.assertEqual(result.passed_count, 1)
        self.assertIn("min.x", result.failures()[0].detail)


class UndeterminedTests(unittest.TestCase):
    def test_a_crashed_inspection_is_undetermined_not_a_defect(self):
        # Scoring tooling breakage as model error makes the number move for the
        # wrong reasons.
        runner = block_runner({("validate", BLOCK): fixtures.INSPECTION_CRASHED})
        result = evaluate(spec_with(ValidSolid()), BLOCK, runner)
        failure = result.failures()[0]
        self.assertEqual(failure.code, FailureCode.INSPECTION_FAILED)
        self.assertTrue(failure.undetermined)
        self.assertEqual(result.defect_count, 0)
        self.assertEqual(result.undetermined_count, 1)
        self.assertIn("bad radius", failure.detail)

    def test_an_unresolved_selector_is_its_own_state(self):
        argv = ("measure", BLOCK, "--from", "#f999", "--to", "#f8", "--axis", "z")
        runner = block_runner({argv: fixtures.BLOCK_MEASURE_BAD_REF})
        spec = spec_with(Distance(from_ref="#f999", to_ref="#f8", axis="z", value=20.0))
        failure = evaluate(spec, BLOCK, runner).failures()[0]
        self.assertEqual(failure.code, FailureCode.SELECTOR_UNRESOLVED)
        self.assertIn("did not resolve", failure.detail)

    def test_undetermined_never_counts_as_a_pass(self):
        runner = block_runner({("validate", BLOCK): fixtures.INSPECTION_CRASHED})
        result = evaluate(spec_with(ValidSolid(), Size(x=100.0)), BLOCK, runner)
        self.assertFalse(result.ok)
        self.assertEqual(result.passed_count, 1)
        self.assertEqual(result.score, 0.5)

    def test_unexpected_payload_shape_is_undetermined_not_a_defect(self):
        # Version skew between IRIN and the CAD CLI is not a bad model.
        runner = block_runner({("refs", BLOCK, "--facts"): {"ok": True, "tokens": []}})
        failure = evaluate(spec_with(Size(x=100.0)), BLOCK, runner).failures()[0]
        self.assertEqual(failure.code, FailureCode.INSPECTION_FAILED)
        self.assertIn("unexpected inspect output", failure.detail)

    def test_one_broken_inspection_is_reported_against_every_assertion_using_it(self):
        runner = block_runner({("refs", BLOCK, "--facts"): fixtures.INSPECTION_CRASHED})
        result = evaluate(spec_with(Size(x=100.0), PartCount(value=1)), BLOCK, runner)
        self.assertEqual(result.undetermined_count, 2)


class AssemblyTests(unittest.TestCase):
    def test_a_nine_part_assembly_scores_against_its_own_facts(self):
        runner = RecordedRunner(
            responses_from_pairs(
                {
                    ("refs", GEARS, "--facts"): fixtures.GEARS_FACTS,
                    ("validate", GEARS): fixtures.GEARS_VALIDATE,
                }.items()
            )
        )
        spec = Spec(
            id="planetary-gear-stage",
            prompt="a planetary gear stage: sun, planets, ring and carrier",
            assertions=(
                ValidSolid(),
                PartCount(value=9),
                Size(x=140.0, y=139.6, z=14.0, tolerance=Tolerance.symmetric(0.05)),
            ),
        )
        result = evaluate(spec, GEARS, runner)
        self.assertTrue(result.ok, result.failures())


class FeatureAssertionTests(unittest.TestCase):
    """The assertions engineering prompts are actually made of."""

    def _runner(self, payload=None):
        return RecordedRunner(
            responses_from_pairs(
                {("features", BLOCK): payload or fixtures.BLOCK_FEATURES}.items()
            )
        )

    def test_four_eight_millimetre_through_holes_pass(self):
        spec = spec_with(HoleCount(value=4, diameter=8.0, through=True))
        self.assertTrue(evaluate(spec, BLOCK, self._runner()).ok)

    def test_every_feature_assertion_shares_one_inspection(self):
        # Feature recognition walks every face in the solid, so paying for it
        # once per spec rather than once per claim is the whole design.
        runner = self._runner()
        spec = spec_with(
            HoleCount(value=4, diameter=8.0),
            HoleCount(value=4),
            BoltCircle(diameter=80.622577, count=4),
        )
        evaluate(spec, BLOCK, runner)
        self.assertEqual(runner.call_count("features"), 1)

    def test_a_wrong_diameter_names_the_diameters_that_are_present(self):
        # "found 0" alone leaves the reader guessing. The sizes actually in the
        # part are what turn a failure into a number to change.
        spec = spec_with(HoleCount(value=4, diameter=6.6))
        failure = evaluate(spec, BLOCK, self._runner()).failures()[0]
        self.assertEqual(failure.code, FailureCode.COUNT_MISMATCH)
        self.assertIn("hole diameters present: [8.0]", failure.detail)

    def test_a_part_with_no_holes_says_so_plainly(self):
        empty = dict(fixtures.BLOCK_FEATURES, features=[], patterns=[], holeCount=0)
        failure = evaluate(spec_with(HoleCount(value=2)), BLOCK, self._runner(empty)).failures()[0]
        self.assertIn("no holes at all", failure.detail)

    def test_the_through_filter_excludes_blind_holes(self):
        blind = dict(
            fixtures.BLOCK_FEATURES,
            features=[dict(f, through=False) for f in fixtures.BLOCK_FEATURES["features"]],
        )
        runner = self._runner(blind)
        self.assertTrue(evaluate(spec_with(HoleCount(value=4, through=False)), BLOCK, runner).ok)
        self.assertFalse(evaluate(spec_with(HoleCount(value=4, through=True)), BLOCK, runner).ok)

    def test_a_rectangular_pattern_is_refused_as_a_bolt_circle(self):
        # The pattern in this fixture has exactly the asserted count and pitch
        # circle. It still must not pass, because it is not evenly spaced, and
        # a naive circle fit would have called it a bolt circle.
        spec = spec_with(BoltCircle(diameter=80.622577, count=4, hole_diameter=8.0))
        result = evaluate(spec, BLOCK, self._runner())
        self.assertFalse(result.ok)
        self.assertIn("not evenly spaced", result.failures()[0].detail)

    def test_a_real_bolt_circle_passes(self):
        runner = RecordedRunner(
            responses_from_pairs({("features", GEARS): fixtures.HUB_FEATURES}.items())
        )
        spec = Spec(
            id="hub",
            prompt="four M5 clearance holes on a 39 mm bolt circle",
            assertions=(BoltCircle(diameter=39.0, count=4, hole_diameter=5.5),),
        )
        self.assertTrue(evaluate(spec, GEARS, runner).ok, "a uniform pattern must pass")

    def test_a_boss_is_not_counted_as_a_hole(self):
        runner = RecordedRunner(
            responses_from_pairs({("features", GEARS): fixtures.HUB_FEATURES}.items())
        )
        spec = Spec(id="hub", prompt="hub", assertions=(HoleCount(value=5),))
        self.assertTrue(evaluate(spec, GEARS, runner).ok, "the 54 mm boss must not count")

    def test_a_missing_pattern_says_so_rather_than_listing_nothing(self):
        empty = dict(fixtures.BLOCK_FEATURES, patterns=[])
        spec = spec_with(BoltCircle(diameter=60.0, count=6))
        failure = evaluate(spec, BLOCK, self._runner(empty)).failures()[0]
        self.assertIn("no circular hole pattern found", failure.detail)


class ReportingTests(unittest.TestCase):
    def test_the_result_serializes_with_counts_and_score(self):
        spec = spec_with(ValidSolid(), PartCount(value=3))
        data = evaluate(spec, BLOCK, block_runner()).to_dict()
        self.assertEqual(data["spec"], "block")
        self.assertEqual(data["counts"], {"total": 2, "passed": 1, "defects": 1, "undetermined": 0})
        self.assertEqual(data["score"], 0.5)
        self.assertFalse(data["ok"])

    def test_the_summary_line_flags_undetermined_separately(self):
        runner = block_runner({("validate", BLOCK): fixtures.INSPECTION_CRASHED})
        line = evaluate(spec_with(ValidSolid(), Size(x=100.0)), BLOCK, runner).summary_line()
        self.assertIn("FAIL", line)
        self.assertIn("undetermined", line)

    def test_inspections_actually_run_are_recorded_on_the_result(self):
        result = evaluate(spec_with(ValidSolid(), Size(x=100.0)), BLOCK, block_runner())
        self.assertEqual(len(result.inspections), 2)
        self.assertTrue(any(i.startswith("validate") for i in result.inspections))


if __name__ == "__main__":
    unittest.main()


class FeatureSpacingEvaluationTests(unittest.TestCase):
    """Spacing is measured between axis lines, not between arbitrary points."""

    @staticmethod
    def _features(*holes):
        return {
            "ok": True,
            "features": [
                {
                    "ref": "o1", "name": "p", "kind": kind, "diameter": d,
                    "axis": list(axis), "position": list(pos),
                    "depth": 10.0, "through": True, "complete": True, "faceCount": 1,
                }
                for d, pos, axis, kind in holes
            ],
            "patterns": [],
            "errors": [],
        }

    def _runner(self, payload):
        return RecordedRunner(responses_from_pairs({("features", BLOCK): payload}.items()))

    def test_two_parallel_bores_report_their_centre_distance(self):
        payload = self._features(
            (12.0, (0.0, 0.0, -170.0), (0.0, 0.0, 1.0), "hole"),
            (12.0, (0.0, 0.0, 170.0), (0.0, 0.0, 1.0), "hole"),
        )
        # Both lie on the same axis line, so the perpendicular spacing is zero.
        spec = spec_with(FeatureSpacing(diameter=12.0, value=0.0001))
        self.assertIsNotNone(evaluate(spec, BLOCK, self._runner(payload)))

    def test_depth_along_the_axis_does_not_inflate_the_spacing(self):
        # The trap: two parallel holes starting at different depths. A straight
        # point-to-point distance would include the 5 mm offset and report 60.2.
        payload = self._features(
            (6.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
            (6.0, (60.0, 0.0, 5.0), (0.0, 0.0, 1.0), "hole"),
        )
        spec = spec_with(FeatureSpacing(diameter=6.0, value=60.0, tolerance=Tolerance.symmetric(0.01)))
        result = evaluate(spec, BLOCK, self._runner(payload))
        self.assertTrue(result.ok, result.failures())
        self.assertAlmostEqual(result.results[0].actual, 60.0, places=6)

    def test_three_matching_features_are_ambiguous_rather_than_resolved(self):
        payload = self._features(
            (6.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
            (6.0, (60.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
            (6.0, (30.0, 40.0, 0.0), (0.0, 0.0, 1.0), "hole"),
        )
        failure = evaluate(
            spec_with(FeatureSpacing(diameter=6.0, value=60.0)), BLOCK, self._runner(payload)
        ).failures()[0]
        self.assertIn("exactly 2", failure.detail)
        self.assertIn("found 3", failure.detail)

    def test_non_parallel_features_have_no_single_spacing(self):
        payload = self._features(
            (6.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
            (6.0, (60.0, 0.0, 0.0), (1.0, 0.0, 0.0), "hole"),
        )
        failure = evaluate(
            spec_with(FeatureSpacing(diameter=6.0, value=60.0)), BLOCK, self._runner(payload)
        ).failures()[0]
        self.assertIn("not parallel", failure.detail)

    def test_a_wrong_spacing_reports_the_measured_value(self):
        payload = self._features(
            (6.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
            (6.0, (75.0, 0.0, 0.0), (0.0, 0.0, 1.0), "hole"),
        )
        failure = evaluate(
            spec_with(FeatureSpacing(diameter=6.0, value=60.0)), BLOCK, self._runner(payload)
        ).failures()[0]
        self.assertEqual(failure.code, FailureCode.DIMENSION_OUT_OF_TOLERANCE)
        self.assertAlmostEqual(failure.actual, 75.0, places=6)

    def test_bosses_are_not_measured_when_holes_were_asked_for(self):
        payload = self._features(
            (20.0, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "boss"),
            (20.0, (60.0, 0.0, 0.0), (0.0, 0.0, 1.0), "boss"),
        )
        failure = evaluate(
            spec_with(FeatureSpacing(diameter=20.0, value=60.0)), BLOCK, self._runner(payload)
        ).failures()[0]
        self.assertIn("found 0", failure.detail)
