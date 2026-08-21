# irincad

STEP-first CAD artifact generation runtime for CAD agent skills, built on
[build123d](https://github.com/gumyr/build123d) and OCCT.

The package boundary is intentionally narrow: it owns artifact generation,
validation, selector/topology extraction, mesh settings, source hashing, and the
`irincad-step-artifact` CLI. It also includes small generated-script helpers such
as `irincad.assembly.AssemblyHelper`, which wraps native build123d labels, joints,
and compounds without owning skill-specific UX. Prompts, viewer UI, and snapshot
job orchestration stay in their owning skills.

`irincad` is developed in
[nevodesigns/irin](https://github.com/nevodesigns/irin) and was
previously named `cadpy` inside that repository.

## Public API

The supported import surface is the root `irincad` exports plus the top-level
`irincad.*` modules:

- Generator-script helpers: root exports (`AssemblyHelper`, `MateRelation`,
  `MateTarget`, `label_text`, `label_shape`, `target`,
  `ensure_step_glb_artifact`, `validate_step_glb_artifact`), `irincad.assembly`,
  and `irincad.step_scene` (`import_step`, `load_step_scene`, `located_shape`,
  `occurrence_selector_id`, `scene_occurrence_shape`).
- Generator-script helpers (2D): `irincad.sources` (`load_source_module`) and
  `irincad.flatten` (planar-face projection/unfold, contour emission, kerf
  offsetting) for `.dxf.py` drawing generators.
- Skill CLI surface: `irincad.generation` (`generate_step_targets`,
  `generate_dxf_targets`, `targets_include_output_pairs`), `irincad.catalog`,
  `irincad.metadata`, `irincad.analysis`, `irincad.lookup`, `irincad.cad_ref_syntax`,
  `irincad.selector_types`, `irincad.reporting`, `irincad.cli_logging`,
  `irincad.render`, `irincad.step_artifacts`, `irincad.step_targets`,
  `irincad.step_export`, `irincad.drawing_checks` (DXF drawing validation), and
  `irincad.drawing_render` (DXF render payload + SVG snapshots).
- Process entry points: `irincad-step-artifact`, `python -m irincad.step_artifact_cli`,
  `python -m irincad.step_export_target`, and `python -m irincad.dxf_artifact`.

Everything under `irincad._internal` is private implementation (the STEP scene,
generation, GLB/topology, and export engines live there) with no import
stability between releases; `irincad.generation` and `irincad.step_scene` are
thin facades over those engines that re-export only the supported names.

## Install

Released versions are published to PyPI by the repository's `Release` workflow;
the package version always matches the CAD plugin release version:

```bash
python -m pip install irincad
```

Production skill bundles pin the exact release version in their
`requirements.txt` (for example `irincad==0.4.0`) and keep a vendored copy of
this package as an offline fallback:

```bash
python -m pip install ./scripts/packages/irincad
```

## Local Development

Install it editable into the repo CAD runtime when working on the source
package directly:

```bash
./.venv/bin/python -m pip install -e packages/irincad
```

After that, changes under `packages/irincad/src/irincad` are immediately visible to
local source checkouts that import the package directly.

On `develop`, the CAD skill and root Viewer point at this package through the
development symlinks `skills/cad/scripts/packages/irincad` and
`viewer/packages/irincad`. Keep those links intact with
`scripts/dev/setup-symlinks.sh --check`.

## Production Bundling

Build a wheel and install it into each skill's bundled Python environment during
packaging:

```bash
./.venv/bin/python -m build packages/irincad
python -m pip install packages/irincad/dist/irincad-*.whl
```

The CAD and cad-viewer skills should depend on the package artifact they bundle,
not on `skills/cad` or the repository root. Production packaging vendors
installable packages under `skills/cad/scripts/packages/irincad` and
`skills/cad-viewer/scripts/viewer/packages/irincad`; production packaging can also
set `VIEWER_CAD_PYTHON` to a skill-local Python runtime with this package
installed. Production skill bundles install `irincad==<release version>` from
PyPI first and fall back to the vendored copy when offline.
