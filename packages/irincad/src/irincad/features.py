"""Cylindrical feature recognition: holes, bosses, and the patterns they form.

Nothing else in the toolchain answers "how many holes does this have, and how
big are they". ``inspect refs`` reports face counts and bounds, ``validate``
answers whether a body is sound, and ``interfere`` answers whether two parts
overlap. None of them can check the sentence most engineering requirements are
actually made of: *six M6 clearance holes on a 60 mm bolt circle*.

That gap has a cost beyond inconvenience. A specification that cannot express
its own most common requirement produces checks that pass while the feature the
requirement was about goes unexamined, which reads as a green result and is not
one.

**Telling a hole from a boss.** A cylindrical surface's natural normal points
away from its axis, so a face whose orientation is ``REVERSED`` has its outward
normal pointing *toward* the axis. Material is therefore outside the cylinder
and the void is inside: a hole. ``FORWARD`` means the reverse, and the feature
is a boss or a shaft. This is exact rather than heuristic, and it costs one
enum comparison per face. Verified against a hub whose outer diameter reads as
a boss and whose central bore reads as a hole, in the same solid.

**A rectangular pattern is not a bolt circle.** Four holes at the corners of a
rectangle are all equidistant from its centre, so a circle fits them perfectly.
Reporting that as a bolt circle would be a confident, wrong answer. A bolt
circle also requires equal angular spacing, so that is checked separately and
reported as ``uniform``. The calibration block's four corner holes fit a circle
and are not uniform; a hub's four holes at 90 degree spacing are both.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

# Two axes count as the same line when their direction and their closest point
# to the origin agree to this much. Generous next to CAD precision, tight next
# to any two features a designer meant to be distinct.
AXIS_TOLERANCE_MM = 1e-6

#: Radii within this of each other are the same nominal size. A hole cut by a
#: boolean and a hole cut by a primitive can differ in the last bit.
RADIUS_TOLERANCE_MM = 1e-6

#: A cylinder is complete when its angular spans sum to a full turn less this.
#: A hole split across a seam arrives as two faces of pi each.
FULL_TURN_TOLERANCE_RAD = 1e-6

#: Angular spacing counts as uniform within this. Bolt circles are laid out by
#: division, so real ones land far inside it.
UNIFORM_SPACING_TOLERANCE_DEG = 0.5

#: How many points along a feature's axis are classified when deciding whether
#: it passes through. Enough to catch a thin web between two coaxial blind
#: holes, few enough that the check stays cheap on a large assembly.
THROUGH_SAMPLES = 64

#: Tolerance handed to the solid classifier. Loose enough that a point landing
#: exactly on a face is not called IN by rounding.
THROUGH_CLASSIFIER_TOLERANCE_MM = 1e-7

KIND_HOLE = "hole"
KIND_BOSS = "boss"


def _normalize(vector: Sequence[float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _canonical_direction(direction: Sequence[float]) -> tuple[float, float, float]:
    """A direction and its opposite describe the same axis.

    Flipped so the first significant component is positive, which makes two
    faces of one hole group together no matter which way each was built.
    """
    unit = _normalize(direction)
    for component in unit:
        if abs(component) > 1e-9:
            return unit if component > 0 else (-unit[0], -unit[1], -unit[2])
    return unit


def _point_on_axis_nearest_origin(
    location: Sequence[float], direction: Sequence[float]
) -> tuple[float, float, float]:
    """The one point of an infinite line that identifies it uniquely.

    Two faces of the same hole report different ``Location`` values, one per
    face, so the raw location cannot be a grouping key. The foot of the
    perpendicular from the origin can be.
    """
    unit = _normalize(direction)
    projection = sum(location[i] * unit[i] for i in range(3))
    return tuple(location[i] - projection * unit[i] for i in range(3))


def _quantize(value: float, tolerance: float) -> int:
    return int(round(value / tolerance)) if tolerance > 0 else 0


@dataclass(frozen=True)
class CylindricalFeature:
    """One hole or boss, merged from every face that forms it."""

    ref: str
    name: str
    kind: str
    diameter: float
    axis: tuple[float, float, float]
    #: Where the feature starts, on its axis.
    position: tuple[float, float, float]
    depth: float
    through: bool
    #: False when the cylinder is a partial arc, as at the end of a slot.
    complete: bool
    face_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "name": self.name,
            "kind": self.kind,
            "diameter": round(self.diameter, 6),
            "radius": round(self.diameter / 2.0, 6),
            "axis": [round(v, 6) for v in self.axis],
            "position": [round(v, 6) for v in self.position],
            "depth": round(self.depth, 6),
            "through": self.through,
            "complete": self.complete,
            "faceCount": self.face_count,
        }


@dataclass(frozen=True)
class HolePattern:
    """Holes of one diameter, sharing an axis direction, arranged on a circle."""

    diameter: float
    count: int
    circle_diameter: float
    center: tuple[float, float, float]
    axis: tuple[float, float, float]
    #: True only when the angular spacing is equal. Without this a rectangular
    #: pattern reads as a bolt circle, because a circle fits it perfectly.
    uniform: bool
    max_radius_deviation: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "holeDiameter": round(self.diameter, 6),
            "count": self.count,
            "circleDiameter": round(self.circle_diameter, 6),
            "center": [round(v, 6) for v in self.center],
            "axis": [round(v, 6) for v in self.axis],
            "uniform": self.uniform,
            "maxRadiusDeviation": round(self.max_radius_deviation, 6),
        }


@dataclass(frozen=True)
class _RawCylinder:
    radius: float
    direction: tuple[float, float, float]
    location: tuple[float, float, float]
    v_min: float
    v_max: float
    angular_span: float
    reversed_face: bool


def _raw_cylinders(wrapped: Any) -> list[_RawCylinder]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.TopAbs import TopAbs_Orientation, TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    out: list[_RawCylinder] = []
    explorer = TopExp_Explorer(wrapped, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_SurfaceType.GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis()
            direction = axis.Direction()
            location = cylinder.Location()
            # The face's own UV window, not the surface's. A cylinder surface is
            # infinite in v; only the face knows how deep this hole actually is.
            u_min, u_max, v_min, v_max = BRepTools.UVBounds_s(face)
            out.append(
                _RawCylinder(
                    radius=float(cylinder.Radius()),
                    direction=(direction.X(), direction.Y(), direction.Z()),
                    location=(location.X(), location.Y(), location.Z()),
                    v_min=float(v_min),
                    v_max=float(v_max),
                    angular_span=abs(float(u_max) - float(u_min)),
                    reversed_face=face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED,
                )
            )
        explorer.Next()
    return out


def _bbox_span_along(bbox: Sequence[float], direction: Sequence[float]) -> tuple[float, float]:
    """The extent of an axis-aligned box projected onto a direction."""
    corners = [
        (bbox[0] if i & 1 else bbox[3], bbox[1] if i & 2 else bbox[4], bbox[2] if i & 4 else bbox[5])
        for i in range(8)
    ]
    projections = [sum(corner[k] * direction[k] for k in range(3)) for corner in corners]
    return (min(projections), max(projections))


def _axis_is_clear(
    wrapped: Any,
    anchor: Sequence[float],
    direction: Sequence[float],
    low: float,
    high: float,
    *,
    samples: int = THROUGH_SAMPLES,
) -> bool | None:
    """Is the feature's axis free of material right across the body?

    This is what "through" actually means, and it is worth doing properly
    rather than comparing the cylinder's extent to the body's.

    Almost every real hole is chamfered or filleted at its entry, so its
    cylindrical wall stops short of the face it breaks through. Measuring the
    wall would report a plainly through-drilled hole as blind: the hub in the
    reference corpus spans z 0 to 22 while its bores span 0.7 to 21.3, purely
    because of a 0.7 mm chamfer.

    Sampling the axis instead asks the question directly. Every point along it
    inside the body is outside the material for a through hole, and some point
    is inside the material for a blind one, whatever the entry looks like.

    Returns None when the shape cannot be classified, so a caller can tell "not
    through" apart from "not established".
    """
    try:
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_State

        classifier = BRepClass3d_SolidClassifier(wrapped)
    except Exception:  # noqa: BLE001 - classifier unavailable for this shape
        return None

    if high <= low:
        return None

    try:
        for index in range(samples + 1):
            t = low + (high - low) * index / samples
            point = gp_Pnt(*(anchor[k] + t * direction[k] for k in range(3)))
            classifier.Perform(point, THROUGH_CLASSIFIER_TOLERANCE_MM)
            if classifier.State() == TopAbs_State.TopAbs_IN:
                return False
    except Exception:  # noqa: BLE001 - a classification failure is not a verdict
        return None
    return True


def features_of_shape(
    wrapped: Any,
    *,
    ref: str = "",
    name: str = "",
    bbox: Sequence[float] | None = None,
) -> list[CylindricalFeature]:
    """Every hole and boss in one placed shape.

    Faces are merged by axis line, radius and kind, so a hole split across a
    seam counts once and reports the angular span of the whole thing.
    """
    groups: dict[tuple, list[_RawCylinder]] = {}
    for raw in _raw_cylinders(wrapped):
        direction = _canonical_direction(raw.direction)
        anchor = _point_on_axis_nearest_origin(raw.location, direction)
        key = (
            KIND_HOLE if raw.reversed_face else KIND_BOSS,
            _quantize(raw.radius, RADIUS_TOLERANCE_MM),
            tuple(_quantize(v, AXIS_TOLERANCE_MM) for v in direction),
            tuple(_quantize(v, AXIS_TOLERANCE_MM) for v in anchor),
        )
        groups.setdefault(key, []).append(raw)

    features: list[CylindricalFeature] = []
    for key, members in groups.items():
        kind = key[0]
        radius = members[0].radius
        direction = _canonical_direction(members[0].direction)

        # v is measured from each face's own Location, so convert to a shared
        # frame before taking the union. Without this, two faces of one hole
        # with different Locations would report a nonsense depth.
        spans: list[tuple[float, float]] = []
        for raw in members:
            base = sum(raw.location[i] * direction[i] for i in range(3))
            unit = _normalize(raw.direction)
            sign = 1.0 if sum(unit[i] * direction[i] for i in range(3)) >= 0 else -1.0
            low = base + sign * raw.v_min
            high = base + sign * raw.v_max
            spans.append((min(low, high), max(low, high)))

        start = min(span[0] for span in spans)
        end = max(span[1] for span in spans)
        depth = end - start

        anchor = _point_on_axis_nearest_origin(members[0].location, direction)
        position = tuple(anchor[i] + start * direction[i] for i in range(3))

        total_angle = sum(raw.angular_span for raw in members)
        complete = total_angle >= (2 * math.pi) - FULL_TURN_TOLERANCE_RAD

        through = False
        if bbox is not None and kind == KIND_HOLE:
            body_low, body_high = _bbox_span_along(bbox, direction)
            clear = _axis_is_clear(wrapped, anchor, direction, body_low, body_high)
            through = bool(clear)

        features.append(
            CylindricalFeature(
                ref=ref,
                name=name,
                kind=kind,
                diameter=radius * 2.0,
                axis=direction,
                position=position,
                depth=depth,
                through=through,
                complete=complete,
                face_count=len(members),
            )
        )

    features.sort(key=lambda f: (f.kind, -f.diameter, f.position))
    return features


def hole_patterns(
    features: Iterable[CylindricalFeature],
    *,
    uniform_tolerance_deg: float = UNIFORM_SPACING_TOLERANCE_DEG,
) -> list[HolePattern]:
    """Circular arrangements among holes of equal diameter and parallel axes.

    Three holes is the minimum: any two points lie on infinitely many circles,
    so a pair can always be fitted and the fit would mean nothing.
    """
    grouped: dict[tuple, list[CylindricalFeature]] = {}
    for feature in features:
        if feature.kind != KIND_HOLE:
            continue
        key = (
            _quantize(feature.diameter, RADIUS_TOLERANCE_MM),
            tuple(_quantize(v, AXIS_TOLERANCE_MM) for v in feature.axis),
        )
        grouped.setdefault(key, []).append(feature)

    patterns: list[HolePattern] = []
    for members in grouped.values():
        if len(members) < 3:
            continue
        axis = members[0].axis
        centroid = tuple(
            sum(member.position[i] for member in members) / len(members) for i in range(3)
        )

        radii = []
        angles = []
        basis_u = _perpendicular_to(axis)
        basis_v = _cross(axis, basis_u)
        for member in members:
            offset = tuple(member.position[i] - centroid[i] for i in range(3))
            # Flatten onto the plane the axis is normal to, so a pattern is
            # measured in the plane it was laid out in rather than in 3D.
            along = sum(offset[i] * axis[i] for i in range(3))
            planar = tuple(offset[i] - along * axis[i] for i in range(3))
            u = sum(planar[i] * basis_u[i] for i in range(3))
            v = sum(planar[i] * basis_v[i] for i in range(3))
            radii.append(math.hypot(u, v))
            angles.append(math.degrees(math.atan2(v, u)) % 360.0)

        mean_radius = sum(radii) / len(radii)
        if mean_radius <= 1e-9:
            continue
        max_deviation = max(abs(radius - mean_radius) for radius in radii)

        angles.sort()
        gaps = [
            (angles[(i + 1) % len(angles)] - angles[i]) % 360.0 for i in range(len(angles))
        ]
        expected = 360.0 / len(angles)
        uniform = all(abs(gap - expected) <= uniform_tolerance_deg for gap in gaps)

        patterns.append(
            HolePattern(
                diameter=members[0].diameter,
                count=len(members),
                circle_diameter=mean_radius * 2.0,
                center=centroid,
                axis=axis,
                uniform=uniform,
                max_radius_deviation=max_deviation,
            )
        )

    patterns.sort(key=lambda p: (-p.count, -p.circle_diameter))
    return patterns


def _perpendicular_to(direction: Sequence[float]) -> tuple[float, float, float]:
    reference = (1.0, 0.0, 0.0) if abs(direction[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _normalize(_cross(direction, reference))


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def inspect_features(
    entry: str,
    *,
    refs: Iterable[str] | None = None,
    kind: str = "all",
    min_diameter: float | None = None,
    max_diameter: float | None = None,
) -> dict[str, object]:
    """Public entry point used by ``inspect features``."""
    from irincad.cli_logging import CliLogger
    from irincad.interference import _selected, occurrences_from_scene, scene_label_rows
    from irincad.step_export_target import _resolve_spec_and_scene
    from irincad.step_targets import resolve_step_target

    if kind not in {"all", KIND_HOLE, KIND_BOSS}:
        raise ValueError(f"kind must be one of all, {KIND_HOLE}, {KIND_BOSS}")

    target = resolve_step_target(entry)
    logger = CliLogger("cad")
    repo_root = Path.cwd()
    source_path = target.source_path if str(target.source_path).endswith(".py") else None
    _spec, scene = _resolve_spec_and_scene(
        repo_root,
        target.step_path,
        source_path,
        mesh_tolerance=None,
        mesh_angular_tolerance=None,
        logger=logger,
    )

    occurrences = _selected(
        occurrences_from_scene(scene),
        refs,
        label_rows=scene_label_rows(scene),
        entry_target=str(entry),
    )

    all_features: list[CylindricalFeature] = []
    for occurrence in occurrences:
        all_features.extend(
            features_of_shape(
                occurrence.shape,
                ref=occurrence.ref,
                name=occurrence.name,
                bbox=occurrence.bbox,
            )
        )

    selected = [
        feature
        for feature in all_features
        if (kind == "all" or feature.kind == kind)
        and (min_diameter is None or feature.diameter >= min_diameter)
        and (max_diameter is None or feature.diameter <= max_diameter)
    ]

    holes = [feature for feature in selected if feature.kind == KIND_HOLE]
    patterns = hole_patterns(holes)

    return {
        "ok": True,
        "entry": target.cad_path,
        "occurrenceCount": len(occurrences),
        "holeCount": len(holes),
        "bossCount": sum(1 for feature in selected if feature.kind == KIND_BOSS),
        "features": [feature.as_dict() for feature in selected],
        "patterns": [pattern.as_dict() for pattern in patterns],
        "errors": [],
    }
