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
    features    ->  inspect features

Hole count, hole size and bolt-circle geometry became expressible once
``irincad.features`` could recognise cylindrical features, which is what that
paragraph used to say was missing.

Still absent, for the same reason as before: fillet and chamfer presence, wall
thickness, and feature-level identity in general.
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
class HoleCount(Assertion):
    """How many holes there are, optionally of one size and one kind.

    This is the assertion most engineering prompts are actually made of. "Four
    8 mm through-holes" is checkable as ``value=4, diameter=8.0, through=True``,
    and until this existed a spec for that part could only check its outline.

    The filters narrow which holes count rather than adding separate claims, so
    "four 8 mm holes and two 5 mm holes" is two assertions that each say
    something exact, instead of one that says six holes and means nothing about
    their sizes.
    """

    kind: ClassVar[str] = "hole_count"
    source: ClassVar[str] = "features"

    value: int = 0
    #: Restrict the count to holes of this diameter. None counts every hole.
    diameter: float | None = None
    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.05))
    #: Restrict to through holes (True) or blind ones (False). None counts both.
    through: bool | None = None

    def __post_init__(self) -> None:
        if self.diameter is not None and self.diameter <= 0:
            raise SpecError(f"hole_count.diameter: must be positive, got {self.diameter}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.diameter is not None:
            out["diameter"] = self.diameter
            out["tolerance"] = self.tolerance.to_dict()
        if self.through is not None:
            out["through"] = self.through
        return out

    def describe(self) -> str:
        bits = f"exactly {self.value} hole{'' if self.value == 1 else 's'}"
        if self.diameter is not None:
            bits += f" of {self.diameter:g} mm"
        if self.through is True:
            bits += ", through"
        elif self.through is False:
            bits += ", blind"
        return bits

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "HoleCount":
        if "value" not in data:
            raise SpecError(f"{path}.value: required for hole_count")
        through = data.get("through")
        if through is not None:
            through = _require_bool(through, f"{path}.through")
        diameter = data.get("diameter")
        return cls(
            value=_require_positive_int(data["value"], f"{path}.value"),
            diameter=None if diameter is None else _require_number(diameter, f"{path}.diameter"),
            tolerance=Tolerance.from_value(data.get("tolerance", 0.05), path=f"{path}.tolerance"),
            through=through,
        )


@dataclass(frozen=True)
class BossCount(Assertion):
    """How many external cylinders there are, optionally of one diameter.

    The way to state a round part's outer diameter exactly. A bounding box
    cannot do it: bbox extents are read from the tessellated topology, so an
    80 mm flange measures 79.95 and a 30 mm sleeve measures 29.981. Those are
    faceting artifacts, not the part being undersize, and a spec that tolerated
    them would have to be loose enough to accept a genuinely wrong diameter.

    A recognised cylinder carries its radius from the surface itself, so the
    same flange reports exactly 80.0. Prefer this over ``size`` whenever the
    dimension being specified is round.
    """

    kind: ClassVar[str] = "boss_count"
    source: ClassVar[str] = "features"

    value: int = 0
    diameter: float | None = None
    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.05))

    def __post_init__(self) -> None:
        if self.diameter is not None and self.diameter <= 0:
            raise SpecError(f"boss_count.diameter: must be positive, got {self.diameter}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.diameter is not None:
            out["diameter"] = self.diameter
            out["tolerance"] = self.tolerance.to_dict()
        return out

    def describe(self) -> str:
        bits = f"exactly {self.value} external cylinder{'' if self.value == 1 else 's'}"
        if self.diameter is not None:
            bits += f" of {self.diameter:g} mm"
        return bits

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "BossCount":
        if "value" not in data:
            raise SpecError(f"{path}.value: required for boss_count")
        diameter = data.get("diameter")
        return cls(
            value=_require_positive_int(data["value"], f"{path}.value"),
            diameter=None if diameter is None else _require_number(diameter, f"{path}.diameter"),
            tolerance=Tolerance.from_value(data.get("tolerance", 0.05), path=f"{path}.tolerance"),
        )


@dataclass(frozen=True)
class BoltCircle(Assertion):
    """Holes of one size, evenly spaced on a circle of a given diameter.

    The canonical mechanical interface, and the reason a flange drawing is one
    line of text. Checking it needs three facts together: the pitch circle
    diameter, how many holes sit on it, and that they are evenly spaced.

    Even spacing is not decoration. Four holes at the corners of a rectangle are
    all equidistant from its centre, so a circle fits them perfectly and calling
    that a bolt circle would be a confident wrong answer. An assertion of this
    kind is satisfied only by a pattern the inspection reports as uniform.
    """

    kind: ClassVar[str] = "bolt_circle"
    source: ClassVar[str] = "features"

    diameter: float = 0.0
    count: int = 0
    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.2))
    #: Optionally pin the size of the holes on the circle as well.
    hole_diameter: float | None = None
    hole_tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.05))

    def __post_init__(self) -> None:
        if self.diameter <= 0:
            raise SpecError(f"bolt_circle.diameter: must be positive, got {self.diameter}")
        if self.count < 3:
            raise SpecError(
                f"bolt_circle.count: needs at least 3 holes, got {self.count}. "
                "Any two points lie on infinitely many circles, so a pair cannot "
                "establish a pitch circle."
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "diameter": self.diameter,
            "count": self.count,
            "tolerance": self.tolerance.to_dict(),
        }
        if self.hole_diameter is not None:
            out["hole_diameter"] = self.hole_diameter
            out["hole_tolerance"] = self.hole_tolerance.to_dict()
        return out

    def describe(self) -> str:
        bits = f"{self.count} holes on a {self.diameter:g} mm bolt circle"
        if self.hole_diameter is not None:
            bits += f", each {self.hole_diameter:g} mm"
        return bits

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "BoltCircle":
        for required in ("diameter", "count"):
            if required not in data:
                raise SpecError(f"{path}.{required}: required for bolt_circle")
        hole_diameter = data.get("hole_diameter")
        return cls(
            diameter=_require_number(data["diameter"], f"{path}.diameter"),
            count=_require_positive_int(data["count"], f"{path}.count"),
            tolerance=Tolerance.from_value(data.get("tolerance", 0.2), path=f"{path}.tolerance"),
            hole_diameter=None
            if hole_diameter is None
            else _require_number(hole_diameter, f"{path}.hole_diameter"),
            hole_tolerance=Tolerance.from_value(
                data.get("hole_tolerance", 0.05), path=f"{path}.hole_tolerance"
            ),
        )


@dataclass(frozen=True)
class FeatureSpacing(Assertion):
    """Centre-to-centre distance between the two features of a given size.

    The dimension assemblies are actually specified by. A shock absorber is
    sold by its eye-to-eye length, a link by its hole centres, a bearing block
    by its bolt spacing. ``bolt_circle`` covers the radial case and nothing
    covered the linear one.

    Why this exists when ``distance`` already measures between two references:
    ``distance`` addresses geometry by selector ref, and a ref belongs to one
    model's topology tree. An agent's assembly has entirely different refs, so a
    ref-addressed dimension is checkable on the reference alone and useless in a
    task. Addressing features by size instead makes the same requirement
    checkable on any model that satisfies it.

    Exactly two matching features are required. Three holes of one diameter have
    three pairwise spacings and no single answer, so that is reported as
    ambiguous rather than resolved by picking one.
    """

    kind: ClassVar[str] = "feature_spacing"
    source: ClassVar[str] = "features"

    diameter: float = 0.0
    value: float = 0.0
    tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.1))
    #: Which kind of cylinder to measure between.
    feature: str = "hole"
    diameter_tolerance: Tolerance = field(default_factory=lambda: Tolerance.symmetric(0.05))

    def __post_init__(self) -> None:
        if self.diameter <= 0:
            raise SpecError(f"feature_spacing.diameter: must be positive, got {self.diameter}")
        if self.value <= 0:
            raise SpecError(f"feature_spacing.value: must be positive, got {self.value}")
        if self.feature not in ("hole", "boss"):
            raise SpecError(
                f"feature_spacing.feature: expected 'hole' or 'boss', got {self.feature!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "diameter": self.diameter,
            "value": self.value,
            "tolerance": self.tolerance.to_dict(),
        }
        if self.feature != "hole":
            out["feature"] = self.feature
        return out

    def describe(self) -> str:
        noun = "bores" if self.feature == "hole" else "external cylinders"
        return f"the two {self.diameter:g} mm {noun} are {self.value:g} mm apart"

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: str) -> "FeatureSpacing":
        for required in ("diameter", "value"):
            if required not in data:
                raise SpecError(f"{path}.{required}: required for feature_spacing")
        feature = data.get("feature", "hole")
        if not isinstance(feature, str):
            raise SpecError(f"{path}.feature: expected 'hole' or 'boss'")
        return cls(
            diameter=_require_number(data["diameter"], f"{path}.diameter"),
            value=_require_number(data["value"], f"{path}.value"),
            tolerance=Tolerance.from_value(data.get("tolerance", 0.1), path=f"{path}.tolerance"),
            feature=feature,
            diameter_tolerance=Tolerance.from_value(
                data.get("diameter_tolerance", 0.05), path=f"{path}.diameter_tolerance"
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
    HoleCount,
    BossCount,
    BoltCircle,
    FeatureSpacing,
    Distance,
)

REGISTRY: dict[str, type[Assertion]] = {cls.kind: cls for cls in _KINDS}

SUPPORTED_KINDS: tuple[str, ...] = tuple(sorted(REGISTRY))

SOURCES: tuple[str, ...] = ("validate", "facts", "interfere", "measure", "features")


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
