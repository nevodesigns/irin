"""Unit tests for the save-dialog env hooks and the irincad subprocess bridge."""

import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from server_py import irincad_bridge, save_dialog  # noqa: E402

_WORKTREE = pathlib.Path(__file__).resolve().parents[3]


class SaveDialogEnvHooks(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("VIEWER_SAVE_DIALOG_FORCE_PATH", "VIEWER_DISABLE_NATIVE_SAVE_DIALOG")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_forced_path(self):
        os.environ["VIEWER_SAVE_DIALOG_FORCE_PATH"] = "/tmp/out.stl"
        self.assertEqual(save_dialog.pick_save_destination(), {"path": "/tmp/out.stl"})

    def test_forced_cancel(self):
        os.environ["VIEWER_SAVE_DIALOG_FORCE_PATH"] = "__cancel__"
        self.assertEqual(save_dialog.pick_save_destination(), {"cancelled": True})

    def test_disabled_is_unsupported(self):
        os.environ["VIEWER_DISABLE_NATIVE_SAVE_DIALOG"] = "1"
        self.assertEqual(save_dialog.pick_save_destination(), {"unsupported": True})


class CadpyPythonpath(unittest.TestCase):
    def test_discovers_irincad_src(self):
        if not (_WORKTREE / "packages" / "irincad" / "src").is_dir():
            self.skipTest("packages/irincad/src not present")
        pp = irincad_bridge.irincad_pythonpath(str(_WORKTREE))
        self.assertIn(os.path.join("packages", "irincad", "src"), pp)

    def test_irincad_runtime_probe_checks_required_imports(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(irincad_bridge.subprocess, "run", return_value=completed) as run:
            result = irincad_bridge.probe_irincad_runtime(str(_WORKTREE))
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-c"])
        self.assertIn("import OCP", command[2])
        self.assertIn("import build123d", command[2])
        self.assertIn("import irincad.step_artifact_cli", command[2])

    def test_irincad_runtime_probe_preserves_import_failure(self):
        completed = subprocess.CompletedProcess(
            [], 1, stdout="", stderr="ModuleNotFoundError: No module named 'OCP'"
        )
        with mock.patch.object(irincad_bridge.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "No module named 'OCP'"):
                irincad_bridge.require_irincad_runtime(str(_WORKTREE))


if __name__ == "__main__":
    unittest.main()
