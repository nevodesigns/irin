"""A spec: one engineering task, and what its result has to satisfy.

This is the structure that stops engineering intent from living only inside a
model's context window. The prompt says what to build; the assertions say what
"built correctly" means, in numbers a machine can check without a human looking
at a picture.

The same object serves two jobs that are usually built twice. A benchmark task
is a spec whose prompt is handed to an agent and whose assertions are the answer
key. A production requirement is a spec whose assertions run against the
artifact every time it is regenerated. Keeping one shape for both is what makes
a benchmark result mean something about real work.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from irinspec.assertions import Assertion, assertion_from_dict
from irinspec.errors import SpecError

# Millimetres only, for now. cadgen models in millimetres and the CAD skill
# defaults to them, so accepting an alternative unit here would either be a lie
# or a silent scale factor applied somewhere downstream. When unit conversion is
# implemented, this becomes a real set.
SUPPORTED_UNITS = ("mm",)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class Spec:
    """One task and its acceptance criteria."""

    id: str
    prompt: str
    assertions: tuple[Assertion, ...]
    units: str = "mm"
    repair_budget: int = 0
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_PATTERN.match(self.id):
            raise SpecError(
                f"id: expected a lowercase slug such as 'flange-6x-m6', got {self.id!r}. "
                "Ids name result files and appear in reports, so they stay filesystem-safe."
            )
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise SpecError(
                "prompt: required and non-empty. A spec with assertions but no prompt "
                "cannot be handed to an agent, which is half of what a spec is for."
            )
        if self.units not in SUPPORTED_UNITS:
            raise SpecError(
                f"units: {self.units!r} is not supported. Only {list(SUPPORTED_UNITS)} is, "
                "because the CAD runtime models in millimetres and converting silently "
                "would misreport every dimensional check."
            )
        if not self.assertions:
            raise SpecError(
                f"{self.id}: at least one assertion is required. A spec with none passes "
                "unconditionally, which reads as a green result while checking nothing."
            )
        if not isinstance(self.repair_budget, int) or isinstance(self.repair_budget, bool):
            raise SpecError("repair_budget: expected an integer")
        if self.repair_budget < 0:
            raise SpecError(f"repair_budget: must be zero or more, got {self.repair_budget}")

    # -- grouping -------------------------------------------------------------

    def by_source(self) -> dict[str, tuple[Assertion, ...]]:
        """Assertions grouped by the inspection that answers them.

        The evaluator runs one inspection per source rather than one per
        assertion. On a large assembly the interference test alone can dominate
        the run, so paying for it once per spec instead of once per claim is the
        difference between a benchmark that finishes and one that does not.
        """
        grouped: dict[str, list[Assertion]] = {}
        for assertion in self.assertions:
            grouped.setdefault(assertion.source, []).append(assertion)
        return {source: tuple(items) for source, items in grouped.items()}

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "prompt": self.prompt,
            "units": self.units,
        }
        if self.repair_budget:
            out["repair_budget"] = self.repair_budget
        if self.notes:
            out["notes"] = self.notes
        out["assertions"] = [a.to_dict() for a in self.assertions]
        return out

    @classmethod
    def from_dict(cls, data: object, *, path: str = "spec") -> "Spec":
        if not isinstance(data, dict):
            raise SpecError(f"{path}: expected an object, got {type(data).__name__}")

        unknown = set(data) - {"id", "prompt", "units", "repair_budget", "notes", "assertions"}
        if unknown:
            raise SpecError(
                f"{path}: unknown key(s) {sorted(unknown)}. "
                "A misspelled key would otherwise be ignored, and the spec would "
                "quietly check less than its author intended."
            )

        for required in ("id", "prompt", "assertions"):
            if required not in data:
                raise SpecError(f"{path}.{required}: required")

        raw_assertions = data["assertions"]
        if not isinstance(raw_assertions, list):
            raise SpecError(f"{path}.assertions: expected a list")

        assertions = tuple(
            assertion_from_dict(item, f"{path}.assertions[{i}]")
            for i, item in enumerate(raw_assertions)
        )

        return cls(
            id=data["id"],
            prompt=data["prompt"],
            assertions=assertions,
            units=data.get("units", "mm"),
            repair_budget=data.get("repair_budget", 0),
            notes=data.get("notes", ""),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent) + "\n"

    @classmethod
    def from_json(cls, text: str, *, path: str = "spec") -> "Spec":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
        return cls.from_dict(data, path=path)


def load_spec(path: str | Path) -> Spec:
    """Read one spec file. The path is used in errors so failures name the file."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"{p}: cannot be read: {exc}") from exc
    return Spec.from_json(text, path=str(p))


def dump_spec(spec: Spec, path: str | Path) -> Path:
    """Write one spec file, creating parent directories."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(spec.to_json(), encoding="utf-8")
    return p


def load_specs(paths: Iterable[str | Path]) -> tuple[Spec, ...]:
    """Read several specs, refusing duplicate ids.

    Duplicate ids are rejected rather than last-one-wins because a benchmark
    keyed by id would silently drop a task, and the run would still report a
    total that looked plausible.
    """
    specs: list[Spec] = []
    seen: dict[str, str] = {}
    for path in paths:
        spec = load_spec(path)
        if spec.id in seen:
            raise SpecError(
                f"duplicate spec id {spec.id!r} in {path} and {seen[spec.id]}. "
                "Ids key benchmark results, so a duplicate would drop a task silently."
            )
        seen[spec.id] = str(path)
        specs.append(spec)
    return tuple(specs)
