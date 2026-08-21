"""Assertions: the checkable claims a spec makes about a generated artifact.

Every kind defined here is one IRIN can actually measure today, from output the
CAD inspection CLI already produces. That constraint is deliberate. A schema
that accepts ``{"kind": "hole_count", "value": 6}`` while nothing can count
holes produces specs that look rigorous and silently check nothing, which is
worse than having no spec at all. Kinds arrive here when their evaluator does,
not before.

Each kind records the ``source`` that supplies its fact, so the evaluator can
group a spec's assertions by the command that answers them and pay for each
inspection once rather than once per assertion:

    validate    ->  inspect validate
    facts       ->  inspect refs --facts
    interfere   ->  inspect interfere
    measure     ->  inspect measure

Not yet expressible, and intentionally absent until the measurement exists:
hole count and diameter, bolt-circle geometry, fillet and chamfer presence,
wall thickness, and feature-level identity in general. Those need feature
recognition over the B-rep, which is real work, not a schema entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from irinspec.errors import SpecError
from irinspec.tolerance import Tolerance

AXES = ("x", "y", "z")


def _require_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{path}: expected a number, got {type(value).__name__}")
    return float(value)


def _require_positive_int(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{path}: expected an integer, got {type(value).__name__}")
    if value < 0:
        raise SpecError(f"{path}: expected a count of zero or more, got {value}")
    return value


def _require_bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{path}: expected true or false, got {type(value).__name__}")
    return value


def _require_ref(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"{path}: expected a non-empty selector ref such as '#o1.2.f1'")
    ref = value.strip()
    if not ref.startswith("#"):
        raise SpecError(f"{path}: selector refs start with '#', got {ref!r}")
    return ref


@dataclass(frozen=True)
class Assertion:
    """Base class. Subclasses declare ``kind`` and ``source``."""

    kind: ClassVar[str] = ""
    source: ClassVar[str] = ""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def describe(self) -> str:
        """One line, readable in a failure report without the JSON beside it."""
        raise NotImplementedError


@dataclass(frozen=True)
class ValidSolid(Assertion):
    """Every occurrence is a sound solid.

    This is the assertion that catches the failure mode a screenshot cannot: an
    inverted solid renders as a hole in the world and passes a topology check,
    and an open shell looks identical to a closed one from outside.
    """

    kind: ClassVar[str] = "valid_solid"
    source: ClassVar[str] = "validate"

    allow_open: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.allow_open:
            out["allow_open"] = True
        return out

    def describe(self) -> str:
        if self.allow_open:
            return "geometry is sound, with open shells permitted"
        return "geometry is a closed, positive-volume, non-self-intersecting solid"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "ValidSolid":
        return cls(allow_open=_require_bool(data.get("allow_open", False), f"{path}.allow_open"))


@dataclass(frozen=True)
class Size(Assertion):
    """Overall bounding-box extents, per axis.

    Any subset of axes may be given. A part specified only by its plate
    thickness should assert ``z`` alone rather than being forced to invent
    values for ``x`` and ``y`` it does not care about.
    """

    kind: ClassVar[str] = "size"
    source: ClassVar[str] = "facts"

    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.1))
    x: float | None = None
    y: float | None = None
    z: float | None = None

    def __post_init__(self) -> None:
        if self.x is None and self.y is None and self.z is None:
            raise SpecError("size: give at least one of x, y, z")
        for axis in AXES:
            value = getattr(self, axis)
            if value is not None and value <= 0:
                raise SpecError(f"size.{axis}: an extent must be positive, got {value}")

    def axes(self) -> dict[str, float]:
        return {a: getattr(self, a) for a in AXES if getattr(self, a) is not None}

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        out.update(self.axes())
        out["tolerance"] = self.tolerance.to_dict()
        return out

    def describe(self) -> str:
        parts = ", ".join(f"{a}={v}" for a, v in self.axes().items())
        return f"bounding box {parts} (mm)"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "Size":
        given = {a: _require_number(data[a], f"{path}.{a}") for a in AXES if a in data}
        return cls(
            tolerance=Tolerance.from_value(data.get("tolerance", 0.1), path=f"{path}.tolerance"),
            **given,
        )


@dataclass(frozen=True)
class Bounds(Assertion):
    """Where the part sits in space, not merely how big it is.

    Size alone cannot catch a part modelled correctly and then placed at the
    wrong origin, which is the single most common assembly defect.
    """

    kind: ClassVar[str] = "bounds"
    source: ClassVar[str] = "facts"

    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.1))
    min: tuple[float, float, float] | None = None
    max: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.min is None and self.max is None:
            raise SpecError("bounds: give at least one of min, max")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.min is not None:
            out["min"] = list(self.min)
        if self.max is not None:
            out["max"] = list(self.max)
        out["tolerance"] = self.tolerance.to_dict()
        return out

    def describe(self) -> str:
        bits = []
        if self.min is not None:
            bits.append(f"min {list(self.min)}")
        if self.max is not None:
            bits.append(f"max {list(self.max)}")
        return "bounding box corner " + " and ".join(bits) + " (mm)"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "Bounds":
        def corner(name: str) -> tuple[float, float, float] | None:
            if name not in data:
                return None
            raw = data[name]
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                raise SpecError(f"{path}.{name}: expected three numbers [x, y, z]")
            return tuple(_require_number(v, f"{path}.{name}[{i}]") for i, v in enumerate(raw))

        return cls(
            tolerance=Tolerance.from_value(data.get("tolerance", 0.1), path=f"{path}.tolerance"),
            min=corner("min"),
            max=corner("max"),
        )


@dataclass(frozen=True)
class _ExactCount(Assertion):
    """Shared shape for the topology counts. Not registered on its own."""

    value: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value}

    def describe(self) -> str:
        noun = self.kind.replace("_count", "").replace("_", " ")
        return f"exactly {self.value} {noun}{'' if self.value == 1 else 's'}"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str):
        if "value" not in data:
            raise SpecError(f"{path}.value: required for {cls.kind}")
        return cls(value=_require_positive_int(data["value"], f"{path}.value"))


@dataclass(frozen=True)
class PartCount(_ExactCount):
    """How many leaf parts the artifact contains.

    Named for what the inspection actually reports. ``refs --facts`` counts leaf
    occurrences in the assembly tree, so this catches an assembly that lost or
    duplicated a component. It does NOT count solids inside one occurrence: a
    failed boolean that leaves two disjoint bodies in a single part is still one
    leaf occurrence and passes this check.

    Counting true solids needs the per-occurrence figure that ``validate``
    computes but only reports for occurrences that fail, so a ``solid_count``
    assertion would have to claim more than it could show. It is absent until
    that number is exposed for passing occurrences too.
    """

    kind: ClassVar[str] = "part_count"
    source: ClassVar[str] = "facts"


@dataclass(frozen=True)
class FaceCount(_ExactCount):
    """Exact face count. A regression signal, not a design requirement.

    Use it to detect that a model changed shape, not to specify one: many
    correct constructions of the same part differ here, so it belongs in a
    regression spec rather than a task spec.
    """

    kind: ClassVar[str] = "face_count"
    source: ClassVar[str] = "facts"


@dataclass(frozen=True)
class EdgeCount(_ExactCount):
    """Exact edge count. Same caveat as face count."""

    kind: ClassVar[str] = "edge_count"
    source: ClassVar[str] = "facts"


@dataclass(frozen=True)
class NoInterference(Assertion):
    """No two parts occupy the same space.

    Touching is not overlapping. Neighbouring panels share a face by design and
    the boolean returns hairline slivers for those, so the check needs a volume
    floor below which an overlap counts as contact.
    """

    kind: ClassVar[str] = "no_interference"
    source: ClassVar[str] = "interfere"

    volume_tolerance: float = 1.0

    def __post_init__(self) -> None:
        if self.volume_tolerance < 0:
            raise SpecError(
                f"no_interference.volume_tolerance: must be non-negative, got {self.volume_tolerance}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "volume_tolerance": self.volume_tolerance}

    def describe(self) -> str:
        return f"no part overlaps another by more than {self.volume_tolerance} mm^3"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "NoInterference":
        return cls(
            volume_tolerance=_require_number(
                data.get("volume_tolerance", 1.0), f"{path}.volume_tolerance"
            )
        )


@dataclass(frozen=True)
class ClashCount(Assertion):
    """Exactly this many part-vs-part overlaps, at this volume floor.

    The measured counterpart to ``no_interference``. They answer different
    questions and both are needed.

    ``no_interference`` is a *requirement*: no part may overlap another, and a
    task spec states it because the design says so.

    ``clash_count`` is an *observation*: this assembly has three overlaps today.
    Many real models overlap on purpose, a press fit and a mating test fixture
    among them, and a regression baseline derived from such a model must record
    what it is rather than assert a rule it breaks. Recording the count still
    catches drift, because a fourth overlap appearing is a change worth seeing,
    which asserting zero would never surface: it fails identically before and
    after.

    The floor travels with the count because the two are meaningless apart. A
    different volume floor is a different question and will give a different
    answer on the same geometry.
    """

    kind: ClassVar[str] = "clash_count"
    source: ClassVar[str] = "interfere"

    value: int = 0
    volume_tolerance: float = 1.0

    def __post_init__(self) -> None:
        if self.volume_tolerance < 0:
            raise SpecError(
                f"clash_count.volume_tolerance: must be non-negative, got {self.volume_tolerance}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "volume_tolerance": self.volume_tolerance,
        }

    def describe(self) -> str:
        if self.value == 0:
            return f"no overlap above {self.volume_tolerance} mm^3"
        return (
            f"exactly {self.value} known overlap{'' if self.value == 1 else 's'} "
            f"above {self.volume_tolerance} mm^3"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "ClashCount":
        if "value" not in data:
            raise SpecError(f"{path}.value: required for clash_count")
        return cls(
            value=_require_positive_int(data["value"], f"{path}.value"),
            volume_tolerance=_require_number(
                data.get("volume_tolerance", 1.0), f"{path}.volume_tolerance"
            ),
        )


@dataclass(frozen=True)
class Distance(Assertion):
    """A measured distance between two selector refs along one axis.

    This is how a spec states the relationships that matter but are not extents:
    plate thickness, hole-to-edge offset, the gap between a wheel and a chassis.
    The axis is required rather than inferred, because an inferred axis makes a
    passing check ambiguous about what it actually proved.
    """

    kind: ClassVar[str] = "distance"
    source: ClassVar[str] = "measure"

    from_ref: str = ""
    to_ref: str = ""
    axis: str = "x"
    value: float = 0.0
    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.1))

    def __post_init__(self) -> None:
        if self.axis not in AXES:
            raise SpecError(f"distance.axis: expected one of {list(AXES)}, got {self.axis!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "from": self.from_ref,
            "to": self.to_ref,
            "axis": self.axis,
            "value": self.value,
            "tolerance": self.tolerance.to_dict(),
        }

    def describe(self) -> str:
        return f"{self.from_ref} to {self.to_ref} along {self.axis} is {self.value} mm"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "Distance":
        for required in ("from", "to", "value"):
            if required not in data:
                raise SpecError(f"{path}.{required}: required for distance")
        axis = data.get("axis")
        if not isinstance(axis, str):
            raise SpecError(
                f"{path}.axis: required for distance, one of {list(AXES)}. "
                "An inferred axis makes a passing check ambiguous."
            )
        return cls(
            from_ref=_require_ref(data["from"], f"{path}.from"),
            to_ref=_require_ref(data["to"], f"{path}.to"),
            axis=axis,
            value=_require_number(data["value"], f"{path}.value"),
            tolerance=Tolerance.from_value(data.get("tolerance", 0.1), path=f"{path}.tolerance"),
        )


_KINDS: tuple[type[Assertion], ...] = (
    ValidSolid,
    Size,
    Bounds,
    PartCount,
    FaceCount,
    EdgeCount,
    NoInterference,
    ClashCount,
    Distance,
)

REGISTRY: dict[str, type[Assertion]] = {cls.kind: cls for cls in _KINDS}

SUPPORTED_KINDS: tuple[str, ...] = tuple(sorted(REGISTRY))

SOURCES: tuple[str, ...] = ("validate", "facts", "interfere", "measure")


def assertion_from_dict(data: object, path: str) -> Assertion:
    """Build one assertion, or explain precisely why it cannot be built."""
    if not isinstance(data, dict):
        raise SpecError(f"{path}: expected an object, got {type(data).__name__}")
    kind = data.get("kind")
    if not isinstance(kind, str) or not kind:
        raise SpecError(f"{path}.kind: required, one of {list(SUPPORTED_KINDS)}")
    cls = REGISTRY.get(kind)
    if cls is None:
        raise SpecError(
            f"{path}.kind: {kind!r} is not a checkable assertion. "
            f"Supported: {list(SUPPORTED_KINDS)}. "
            "Kinds are added when their evaluator exists, so that a spec never "
            "appears to check something nothing measures."
        )
    try:
        return cls.from_dict(data, path)  # type: ignore[attr-defined]
    except SpecError as exc:
        # Field parsers already prefix their path. Constructor checks in
        # __post_init__ cannot: they run after the parser has handed the values
        # over and know nothing about where in the document they came from. Left
        # alone they surface as "size: give at least one of x, y, z", which is
        # true and useless in a file with thirty assertions.
        message = str(exc)
        if message.startswith(path):
            raise
        raise SpecError(f"{path}: {message}") from exc
