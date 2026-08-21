"""The IRIN measurement packages must keep their dependency direction.

    irinbench  ->  irineval  ->  irinspec

and none of the three may import ``irincad``.

That last rule is the load-bearing one. ``irineval`` reaches the CAD kernel by
running the ``inspect`` CLI as a separate process, which is what keeps a
segfault inside OpenCascade from taking a whole benchmark run with it, and what
lets a report generator or a CI check read specs and results without installing
build123d. A single convenience import of ``irincad`` would quietly undo both
properties, and nothing else in the repository would notice.

Prose in AGENTS.md cannot enforce that. This can.
"""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"

#: What each package is allowed to import from the others.
ALLOWED = {
    "irinspec": set(),
    "irineval": {"irinspec"},
    "irinbench": {"irinspec", "irineval"},
}

IRIN_PACKAGES = set(ALLOWED) | {"irincad"}


def _source_files(package: str) -> list[Path]:
    root = PACKAGES / package / "src" / package
    return sorted(root.rglob("*.py"))


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


class LayeringTests(unittest.TestCase):
    def test_every_package_directory_exists(self):
        for package in ALLOWED:
            self.assertTrue(
                (PACKAGES / package / "src" / package).is_dir(),
                f"packages/{package}/src/{package} is missing",
            )

    def test_no_irin_package_imports_the_cad_runtime(self):
        for package in ALLOWED:
            for path in _source_files(package):
                self.assertNotIn(
                    "irincad",
                    _imported_top_levels(path),
                    f"{path.relative_to(REPO_ROOT)} imports irincad. The measurement "
                    "packages reach the CAD kernel through the inspect CLI as a "
                    "subprocess, so that a crash cannot take a run with it and a "
                    "reporting tool needs no CAD install.",
                )

    def test_imports_only_flow_downward(self):
        for package, allowed in ALLOWED.items():
            for path in _source_files(package):
                imported = _imported_top_levels(path) & IRIN_PACKAGES
                illegal = imported - allowed - {package}
                self.assertFalse(
                    illegal,
                    f"{path.relative_to(REPO_ROOT)} imports {sorted(illegal)}, which "
                    f"reverses the layering. {package} may import {sorted(allowed) or 'nothing'}.",
                )

    def test_declared_dependencies_match_the_layering(self):
        for package, allowed in ALLOWED.items():
            pyproject = PACKAGES / package / "pyproject.toml"
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            declared = {
                dep.split()[0].split(">")[0].split("=")[0].strip()
                for dep in data["project"].get("dependencies", [])
            }
            self.assertEqual(
                declared & IRIN_PACKAGES,
                allowed,
                f"{pyproject.relative_to(REPO_ROOT)} declares {sorted(declared)}, "
                f"which does not match the allowed layering {sorted(allowed)}",
            )

    def test_irinspec_stays_dependency_free(self):
        # A benchmark runner, a report generator and a CI check all parse specs.
        # One dependency here is one every consumer inherits.
        data = tomllib.loads((PACKAGES / "irinspec" / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            data["project"].get("dependencies", []),
            [],
            "irinspec must stay stdlib only",
        )

    def test_every_irin_package_carries_a_license(self):
        for package in ALLOWED:
            self.assertTrue(
                (PACKAGES / package / "LICENSE").is_file(),
                f"packages/{package}/LICENSE is missing",
            )


if __name__ == "__main__":
    unittest.main()
