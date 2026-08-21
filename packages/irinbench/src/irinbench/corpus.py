"""A benchmark corpus: a set of specs and the artifacts they are bound to.

The binding lives in a manifest rather than inside the specs, because the two
kinds of spec differ exactly here. A **regression** spec is bound to an existing
artifact: it says "this model still measures the way it did". A **task** spec is
not bound to anything, because the whole point is that an agent has to produce
the artifact from the prompt.

Keeping ``Spec`` free of a file path means one object serves both, and a task
spec cannot accidentally inherit a location that quietly turns it into a
regression check.

    benchmarks/<name>/
      corpus.json          manifest: kind, entries, provenance
      specs/<id>.json      one spec per task
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from irinspec import Spec, SpecError, dump_spec, load_spec

#: A regression corpus is derived by measuring existing models. Its assertions
#: record what the geometry currently is, so a rerun detects drift.
KIND_REGRESSION = "regression"

#: A task corpus states intent in the prompt and is scored on what an agent
#: builds from it. Its assertions come from the requirement, not from a model.
KIND_TASK = "task"

KINDS = (KIND_REGRESSION, KIND_TASK)

#: Generator modules that are not buildable entries. ``<name>.step.py`` is an
#: entry; a plain ``<name>.py`` beside it is a shared helper.
ENTRY_SUFFIX = ".step.py"


class CorpusError(RuntimeError):
    """The corpus on disk is malformed or inconsistent with its specs."""


def spec_id_for(entry: str | Path) -> str:
    """A filesystem-safe spec id from a generator path.

    Derived from the stem alone, so ``models/step/parts/l_bracket.step.py``
    becomes ``l-bracket``. Collisions across directories are caught when the
    corpus is assembled rather than silently overwriting a spec.
    """
    stem = Path(entry).name
    if stem.endswith(ENTRY_SUFFIX):
        stem = stem[: -len(ENTRY_SUFFIX)]
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if not slug:
        raise CorpusError(f"cannot derive a spec id from {entry}")
    return slug


def discover_generators(roots: Iterable[str | Path]) -> tuple[Path, ...]:
    """Buildable generator entries under the given directories, sorted.

    Only ``*.step.py`` files directly identify an entry. Helper modules and
    sub-part generators nested inside a showcase project are excluded by taking
    each root non-recursively, so a corpus is an explicit list of directories
    rather than whatever a deep walk happens to find.
    """
    found: list[Path] = []
    for root in roots:
        directory = Path(root)
        if not directory.is_dir():
            raise CorpusError(f"{directory} is not a directory")
        found.extend(sorted(p for p in directory.glob(f"*{ENTRY_SUFFIX}") if p.is_file()))
    return tuple(found)


@dataclass
class Corpus:
    """Specs plus the artifacts they are bound to."""

    name: str
    kind: str
    root: Path
    entries: dict[str, str] = field(default_factory=dict)
    specs: tuple[Spec, ...] = ()
    provenance: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise CorpusError(f"kind must be one of {list(KINDS)}, got {self.kind!r}")
        if self.kind == KIND_REGRESSION:
            missing = [s.id for s in self.specs if s.id not in self.entries]
            if missing:
                raise CorpusError(
                    f"regression specs with no bound artifact: {missing}. "
                    "A regression spec that cannot name its model cannot be rerun."
                )

    @property
    def spec_dir(self) -> Path:
        return self.root / "specs"

    @property
    def manifest_path(self) -> Path:
        return self.root / "corpus.json"

    def entry_for(self, spec: Spec) -> str:
        try:
            return self.entries[spec.id]
        except KeyError:
            raise CorpusError(f"no artifact bound to spec {spec.id!r}") from None

    # -- persistence ----------------------------------------------------------

    def save(self) -> Path:
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        for spec in self.specs:
            dump_spec(spec, self.spec_dir / f"{spec.id}.json")
        manifest = {
            "name": self.name,
            "kind": self.kind,
            "entries": dict(sorted(self.entries.items())),
            "provenance": self.provenance,
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return self.manifest_path

    @classmethod
    def load(cls, root: str | Path) -> "Corpus":
        directory = Path(root)
        manifest_path = directory / "corpus.json"
        if not manifest_path.exists():
            raise CorpusError(f"no corpus manifest at {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{manifest_path}: invalid JSON: {exc}") from exc

        spec_dir = directory / "specs"
        specs: list[Spec] = []
        seen: set[str] = set()
        for path in sorted(spec_dir.glob("*.json")):
            try:
                spec = load_spec(path)
            except SpecError as exc:
                raise CorpusError(str(exc)) from exc
            if spec.id in seen:
                raise CorpusError(f"duplicate spec id {spec.id!r} in {spec_dir}")
            seen.add(spec.id)
            specs.append(spec)

        entries = manifest.get("entries") or {}
        orphaned = sorted(set(entries) - seen)
        if orphaned:
            raise CorpusError(
                f"{manifest_path} binds artifacts to specs that do not exist: {orphaned}. "
                "The manifest and specs/ have drifted apart."
            )

        return cls(
            name=manifest.get("name", directory.name),
            kind=manifest.get("kind", KIND_REGRESSION),
            root=directory,
            entries=dict(entries),
            specs=tuple(specs),
            provenance=manifest.get("provenance") or {},
        )
