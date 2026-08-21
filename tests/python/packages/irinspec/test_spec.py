import json
import tempfile
import unittest
from pathlib import Path

from irinspec import (
    NoInterference,
    Size,
    PartCount,
    Spec,
    SpecError,
    Tolerance,
    ValidSolid,
    dump_spec,
    load_spec,
    load_specs,
)


def a_spec(**overrides) -> Spec:
    base = dict(
        id="calibration-block",
        prompt="100 x 60 x 20 mm block, four 8 mm through-holes, 2 mm top chamfer",
        assertions=(ValidSolid(), Size(x=100.0, y=60.0, z=20.0)),
    )
    base.update(overrides)
    return Spec(**base)


class SpecValidationTests(unittest.TestCase):
    def test_a_spec_with_no_assertions_is_refused(self):
        # It would pass unconditionally, which reads as green while checking nothing.
        with self.assertRaises(SpecError) as ctx:
            a_spec(assertions=())
        self.assertIn("passes unconditionally", str(ctx.exception))

    def test_an_empty_prompt_is_refused(self):
        with self.assertRaises(SpecError) as ctx:
            a_spec(prompt="   ")
        self.assertIn("handed to an agent", str(ctx.exception))

    def test_the_id_must_be_a_filesystem_safe_slug(self):
        for bad in ("Calibration Block", "block/one", "", "-leading"):
            with self.assertRaises(SpecError, msg=bad):
                a_spec(id=bad)

    def test_good_ids_are_accepted(self):
        for good in ("flange-6x-m6", "block.v2", "a", "l_bracket-01"):
            self.assertEqual(a_spec(id=good).id, good)

    def test_non_millimetre_units_are_refused_rather_than_silently_scaled(self):
        with self.assertRaises(SpecError) as ctx:
            a_spec(units="in")
        self.assertIn("millimetres", str(ctx.exception))

    def test_a_negative_repair_budget_is_refused(self):
        with self.assertRaises(SpecError):
            a_spec(repair_budget=-1)


class SpecGroupingTests(unittest.TestCase):
    def test_assertions_group_by_the_inspection_that_answers_them(self):
        # The evaluator pays for one inspection per source, not per assertion.
        spec = a_spec(
            assertions=(
                ValidSolid(),
                Size(x=100.0),
                PartCount(value=1),
                NoInterference(),
            )
        )
        grouped = spec.by_source()
        self.assertEqual(set(grouped), {"validate", "facts", "interfere"})
        self.assertEqual(len(grouped["facts"]), 2)
        self.assertEqual(len(grouped["validate"]), 1)

    def test_grouping_covers_every_assertion_exactly_once(self):
        spec = a_spec(assertions=(ValidSolid(), Size(x=1.0), PartCount(value=2)))
        total = sum(len(group) for group in spec.by_source().values())
        self.assertEqual(total, len(spec.assertions))


class SpecSerializationTests(unittest.TestCase):
    def test_round_trip_through_json(self):
        spec = a_spec(
            repair_budget=2,
            notes="derived from the generator constants",
            assertions=(
                ValidSolid(),
                Size(x=100.0, y=60.0, z=20.0, tolerance=Tolerance.symmetric(0.2)),
                PartCount(value=1),
            ),
        )
        self.assertEqual(Spec.from_json(spec.to_json()), spec)

    def test_defaults_are_omitted_from_the_serialized_form(self):
        data = json.loads(a_spec().to_json())
        self.assertNotIn("repair_budget", data)
        self.assertNotIn("notes", data)
        self.assertEqual(data["units"], "mm")

    def test_a_misspelled_top_level_key_is_refused_rather_than_ignored(self):
        with self.assertRaises(SpecError) as ctx:
            Spec.from_dict(
                {
                    "id": "x",
                    "prompt": "p",
                    "assertions": [{"kind": "valid_solid"}],
                    "assertion": [],
                }
            )
        message = str(ctx.exception)
        self.assertIn("assertion", message)
        self.assertIn("quietly check less", message)

    def test_an_error_names_the_failing_assertion_by_index(self):
        with self.assertRaises(SpecError) as ctx:
            Spec.from_dict(
                {
                    "id": "x",
                    "prompt": "p",
                    "assertions": [{"kind": "valid_solid"}, {"kind": "size"}],
                }
            )
        self.assertIn("assertions[1]", str(ctx.exception))

    def test_invalid_json_reports_line_and_column(self):
        with self.assertRaises(SpecError) as ctx:
            Spec.from_json('{"id": "x",}')
        self.assertIn("line 1", str(ctx.exception))


class SpecFileTests(unittest.TestCase):
    def test_dump_then_load_preserves_the_spec(self):
        spec = a_spec()
        with tempfile.TemporaryDirectory() as tmp:
            path = dump_spec(spec, Path(tmp) / "nested" / "spec.json")
            self.assertTrue(path.exists())
            self.assertEqual(load_spec(path), spec)

    def test_a_missing_file_names_the_path(self):
        with self.assertRaises(SpecError) as ctx:
            load_spec("/nonexistent/spec.json")
        self.assertIn("/nonexistent/spec.json", str(ctx.exception))

    def test_a_malformed_file_names_the_path_not_just_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SpecError) as ctx:
                load_spec(bad)
            self.assertIn("bad.json", str(ctx.exception))

    def test_duplicate_ids_across_files_are_refused(self):
        # Ids key benchmark results, so last-one-wins would drop a task while
        # the run still reported a plausible-looking total.
        with tempfile.TemporaryDirectory() as tmp:
            one = dump_spec(a_spec(), Path(tmp) / "one.json")
            two = dump_spec(a_spec(), Path(tmp) / "two.json")
            with self.assertRaises(SpecError) as ctx:
                load_specs([one, two])
            self.assertIn("duplicate spec id", str(ctx.exception))

    def test_distinct_ids_load_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = dump_spec(a_spec(id="one"), Path(tmp) / "one.json")
            two = dump_spec(a_spec(id="two"), Path(tmp) / "two.json")
            specs = load_specs([one, two])
            self.assertEqual([s.id for s in specs], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
