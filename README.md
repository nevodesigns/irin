<div align="center">

<img src="assets/text-to-cad-demo.gif" alt="Demo of the CAD skill generating and previewing CAD geometry" width="100%">

<br>

<pre>
██╗██████╗ ██╗███╗   ██╗
██║██╔══██╗██║████╗  ██║
██║██████╔╝██║██╔██╗ ██║
██║██╔══██╗██║██║╚██╗██║
██║██║  ██║██║██║ ╚████║
╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
</pre>

An engineering agent that measures what it makes

[![Tests](https://img.shields.io/github/actions/workflow/status/nevodesigns/irin/test.yml?branch=develop&style=for-the-badge&logo=githubactions&logoColor=white&label=Tests)](https://github.com/nevodesigns/irin/actions/workflows/test.yml?query=branch%3Adevelop)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](skills/cad/requirements.txt)
[![STEP](https://img.shields.io/badge/STEP-Export-4A5568?style=for-the-badge)](skills/cad/SKILL.md)
[![URDF](https://img.shields.io/badge/URDF-Robots-6B46C1?style=for-the-badge)](skills/urdf/SKILL.md)
[![SDF](https://img.shields.io/badge/SDF-Simulation-6B46C1?style=for-the-badge)](skills/sdf/SKILL.md)
[![SRDF](https://img.shields.io/badge/SRDF-MoveIt2-6B46C1?style=for-the-badge)](skills/srdf/SKILL.md)

</div>

# IRIN

IRIN is a library of agent skills for generating, inspecting, sourcing, slicing
and handing off CAD and robot-description artifacts from local project files.

It exists to close one gap. A generated CAD file can be syntactically perfect
and still be wrong: the hole in the wrong place, the wall a millimetre too thin,
the bracket that will not accept the motor it was designed around. Loading
without error proves nothing. So IRIN treats every artifact as something to be
measured against a declared expectation, not something to be admired in a
screenshot.

The long-term goal is to be able to say, honestly and reproducibly, how often an
agent turns engineering intent into mechanically correct geometry. That number
does not exist yet for any CAD agent. Building the machinery to produce it is
what IRIN is for.

## Status

The inherited platform is mature and works today: STEP-first parametric
modelling, geometric validity checking, part-vs-part interference detection,
robot-description validation, a local review viewer, and plugin distribution for
four agent runtimes.

The measurement layer IRIN is named for is under construction. Nothing in this
README claims a benchmark result, because no benchmark has been run.

## 🧰 Skills

| Skill        | Summary                                                                                                                                            | Source                                              |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| CAD          | Creates and edits CAD models from plain-language or image requests, with STEP as the main output along with options to export to STL, 3MF and GLB. | [skills/cad](skills/cad/SKILL.md)                   |
| CAD Viewer   | Shows local browser previews for CAD and robot files.                                                                                     | [skills/cad-viewer](skills/cad-viewer/SKILL.md)     |
| step.parts   | Finds off-the-shelf STEP parts like screws, bearings, motors, and connectors.                                                                      | [skills/step-parts](skills/step-parts/SKILL.md)     |
| DXF          | Creates 2D DXF drawings like profiles, templates, gaskets, and cut layouts from Python sources or CAD geometry.                                    | [skills/dxf](skills/dxf/SKILL.md)                   |
| URDF         | Writes robot structure files with links, joints, limits, inertials, and meshes.                                                                    | [skills/urdf](skills/urdf/SKILL.md)                 |
| SRDF         | Adds MoveIt planning groups, end effectors, poses, and collision rules to a URDF.                                                                  | [skills/srdf](skills/srdf/SKILL.md)                 |
| SDF          | Creates simulator models and worlds with frames, physics, sensors, and lights.                                                                     | [skills/sdf](skills/sdf/SKILL.md)                   |
| SendCutSend  | Checks DXF and STEP files before upload to SendCutSend.                                                                                            | [skills/sendcutsend](skills/sendcutsend/SKILL.md)   |
| G-code       | Slices supported mesh files into validated, printer-profiled FDM `.gcode` with real slicer CLIs.                                                   | [skills/gcode](skills/gcode/SKILL.md)               |
| Bambu Labs   | Dry-runs, uploads, and cautiously starts local Bambu Lab print jobs from validated `.gcode`.                                                        | [skills/bambu-labs](skills/bambu-labs/SKILL.md)     |
| Implicit CAD | Creates browser-native implicit CAD models using GLSL signed-distance fields and CAD Viewer raymarch rendering. Experimental.                      | [skills/implicit-cad](skills/implicit-cad/SKILL.md) |

## 💻 Installation

For production use, install or clone from `main`; that branch contains the
generated skill outputs needed by provider installers.

### Skills

```bash
npx skills add nevodesigns/irin
```

**Use the same command to update.** `add` re-fetches the package and overwrites
what is already installed, so it both refreshes existing skills and installs any
skill added in a newer release. `npx skills update` only refreshes skills already
in your lockfile, so it silently misses new ones, which matters here because
releases do add skills.

Neither command removes a skill that was retired; drop one with
`npx skills remove <skill>` if you need to.

### Plugins

Provider-native plugin installs are also available for Codex, Claude Code, and
Grok Build:

```bash
# Codex (requires Codex 0.142.0 or newer)
codex plugin marketplace add nevodesigns/irin
codex plugin add cad@irin
```

Codex resolves this repository-root plugin only from 0.142.0 onward. On older
versions the plugin is skipped silently and never appears in `codex plugin list`;
upgrade with `npm install -g @openai/codex@latest`.

```bash
# Claude Code
claude plugin marketplace add nevodesigns/irin
claude plugin install cad@irin
```

Grok Build uses the existing `.claude-plugin/marketplace.json`; there is no
separate Grok plugin manifest.

```bash
# Grok Build
grok plugin install nevodesigns/irin --trust
grok plugin enable cad
```

Restart your agent if newly installed skills do not appear. For local
development, branch from `develop`, open PRs against `develop`, and use the symlink
workflow in [CONTRIBUTING.md](CONTRIBUTING.md).

## 🛠️ Contributing

Development happens from the `develop` branch; open PRs against `develop`, not `main`.
For local contribution workflow, skill linking, and validation guidance, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Credit

IRIN is a fork of [text-to-cad](https://github.com/earthtojake/text-to-cad) by
Thompson Labs LLC, used under the MIT License. The CAD engine, viewer, robot
description skills and release architecture originate there, and that is a large
and genuinely well-built body of work.

IRIN is a hard fork: it does not track upstream releases and its direction is its
own. See [NOTICE](NOTICE) for the full attribution and the list of inherited
license files, none of which may be removed.
