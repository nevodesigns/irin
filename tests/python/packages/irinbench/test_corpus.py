import json
import tempfile
import unittest
from pathlib import Path

from irinspec import Size, Spec, ValidSolid
from irinbench import KIND_REGRESSION, KIND_TASK, Corpus, CorpusError, discover_generators, spec_id_for


def a_spec(spec_id="widget") -> Spec:
    return Spec(
        id=spec_id,
        prompt="a 40 x 25 x 8 mm block",
        assertions=(ValidSolid(), Size(x=40.0)),
    )


class SpecIdTests(unittest.TestCase):
    def test_the_generator_stem_becomes_a_slug(self):
        self.assertEqual(
            spec_id_for("models/step/parts/rectangular_calibration_block.step.py"),
            "rectangular-calibration-block",
        )

    def test_only_the_step_py_suffix_is_stripped(self):
        self.assertEqual(spec_id_for("models/step/parts/l_bracket.step.py"), "l-bracket")

    def test_a_path_that_slugs_to_nothing_is_refused(self):
        with self.assertRaises(CorpusError):
            spec_id_for("models/step/parts/___.step.py")


class DiscoveryTests(unittest.TestCase):
    def test_helper_modules_are_not_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "block.step.py").write_text("", encoding="utf-8")
            (root / "part_common.py").write_text("", encoding="utf-8")
            found = discover_generators([root])
            self.assertEqual([p.name for p in found], ["block.step.py"])

    def test_discovery_does_not_descend_into_subprojects(self):
        # A showcase project holds dozens of sub-part generators. Sweeping them
        # into a corpus would inflate the count with pieces of one model.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "top.step.py").write_text("", encoding="utf-8")
            nested = root / "showcase"
            nested.mkdir()
            (nested / "wing.step.py").write_text("", encoding="utf-8")
            self.assertEqual([p.name for p in discover_generators([root])], ["top.step.py"])

    def test_a_missing_directory_is_an_error_not_an_empty_corpus(self):
        with self.assertRaises(CorpusError):
            discover_generators(["/definitely/not/here"])


class CorpusPersistenceTests(unittest.TestCase):
    def test_round_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "regression"
            corpus = Corpus(
                name="regression",
                kind=KIND_REGRESSION,
                root=root,
                entries={"widget": "models/widget.step.py"},
                specs=(a_spec(),),
                provenance={"tolerance_mm": 0.01},
            )
            corpus.save()
            loaded = Corpus.load(root)
            self.assertEqual(loaded.name, "regression")
            self.assertEqual(loaded.kind, KIND_REGRESSION)
            self.assertEqual(loaded.entries, {"widget": "models/widget.step.py"})
            self.assertEqual([s.id for s in loaded.specs], ["widget"])
            self.assertEqual(loaded.provenance["tolerance_mm"], 0.01)

    def test_a_regression_spec_must_be_bound_to_an_artifact(self):
        # Otherwise it cannot be rerun, and would sit in the corpus looking
        # like coverage while never being evaluated.
        with self.assertRaises(CorpusError) as ctx:
            Corpus(name="r", kind=KIND_REGRESSION, root=Path("."), entries={}, specs=(a_spec(),))
        self.assertIn("no bound artifact", str(ctx.exception))

    def test_a_task_spec_needs_no_artifact(self):
        # The agent produces it. Requiring one would turn every task into a
        # regression check against an answer that does not exist yet.
        corpus = Corpus(name="t", kind=KIND_TASK, root=Path("."), entries={}, specs=(a_spec(),))
        self.assertEqual(corpus.kind, KIND_TASK)

    def test_manifest_and_specs_drifting_apart_is_caught_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "regression"
            Corpus(
                name="regression",
                kind=KIND_REGRESSION,
                root=root,
                entries={"widget": "models/widget.step.py"},
                specs=(a_spec(),),
            ).save()
            (root / "specs" / "widget.json").unlink()
            with self.assertRaises(CorpusError) as ctx:
                Corpus.load(root)
            self.assertIn("drifted apart", str(ctx.exception))

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(CorpusError):
            Corpus(name="x", kind="whatever", root=Path("."))

    def test_a_missing_manifest_names_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CorpusError) as ctx:
                Corpus.load(tmp)
            self.assertIn("corpus.json", str(ctx.exception))

    def test_a_malformed_spec_file_fails_the_whole_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "regression"
            Corpus(
                name="regression",
                kind=KIND_REGRESSION,
                root=root,
                entries={"widget": "models/widget.step.py"},
                specs=(a_spec(),),
            ).save()
            (root / "specs" / "widget.json").write_text("{ nope", encoding="utf-8")
            with self.assertRaises(CorpusError):
                Corpus.load(root)

    def test_entry_for_names_the_spec_when_the_binding_is_missing(self):
        corpus = Corpus(name="t", kind=KIND_TASK, root=Path("."), entries={}, specs=(a_spec(),))
        with self.assertRaises(CorpusError) as ctx:
            corpus.entry_for(a_spec())
        self.assertIn("widget", str(ctx.exception))

    def test_the_manifest_is_sorted_so_diffs_stay_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "regression"
            Corpus(
                name="regression",
                kind=KIND_REGRESSION,
                root=root,
                entries={"zebra": "z.step.py", "alpha": "a.step.py"},
                specs=(a_spec("zebra"), a_spec("alpha")),
            ).save()
            manifest = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
            self.assertEqual(list(manifest["entries"]), ["alpha", "zebra"])


if __name__ == "__main__":
    unittest.main()
