"""Tolerances: how far an actual value may sit from its nominal and still pass.

Every dimensional claim IRIN makes is a nominal plus a tolerance, never a bare
number. A bare number forces an exact float comparison, which fails on geometry
that is correct: a chamfered edge, a meshed export, and a boolean all move the
last few decimal places, and a check that cannot express "close enough" reports
correct parts as wrong.

Three forms, because engineering drawings use three forms:

* **symmetric** -- ``50 +/- 0.2``, the common case.
* **asymmetric** -- ``50 +0.1 / -0.05``, used wherever the fit only has room to
  err one way. A clearance hole may be oversize but never undersize.
* **relative** -- a fraction of nominal, for values whose scale is not known
  when the tolerance is written. Volume across a family of parts, for instance.

The sign of the deviation is preserved throughout. "0.3 too large" and "0.3 too
small" are different engineering facts, and a report that shows only magnitude
throws away the half that tells you which way to move the parameter.
"""

from __future__ import annotations

from dataclasses import dataclass

from irinspec.errors import SpecError

# Below this, a tolerance is indistinguishable from an exact comparison and will
# reject geometry that is correct. Rejecting it at construction is kinder than
# letting it fail mysteriously against a real model.
MIN_MEANINGFUL_ABSOLUTE = 1e-9


@dataclass(frozen=True)
class Tolerance:
    """An allowed band around a nominal value.

    Held as an explicit ``plus``/``minus`` pair plus an optional ``relative``
    fraction, rather than as a tagged union, so that every form answers the same
    two questions without the caller branching on which kind it is.

    ``plus`` and ``minus`` are both non-negative magnitudes. ``minus`` is how far
    BELOW nominal is acceptable, expressed positively, matching how a drawing
    writes ``+0.1 / -0.05``.
    """

    plus: float = 0.0
    minus: float = 0.0
    relative: float = 0.0

    def __post_init__(self) -> None:
        for name in ("plus", "minus", "relative"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SpecError(f"tolerance.{name} must be a number, got {value!r}")
            if value < 0:
                raise SpecError(
                    f"tolerance.{name} must be a non-negative magnitude, got {value}. "
                    "A tolerance below nominal is written as a positive 'minus'."
                )
        if self.plus == 0 and self.minus == 0 and self.relative == 0:
            raise SpecError(
                "tolerance must allow some band; an exact float comparison rejects "
                "geometry that is correct. Use Tolerance.symmetric(...) with a real value."
            )

    # -- constructors ---------------------------------------------------------

    @classmethod
    def symmetric(cls, value: float) -> "Tolerance":
        """``+/- value``."""
        return cls(plus=value, minus=value)

    @classmethod
    def asymmetric(cls, plus: float, minus: float) -> "Tolerance":
        """``+plus / -minus``, both given as positive magnitudes."""
        return cls(plus=plus, minus=minus)

    @classmethod
    def relative_fraction(cls, fraction: float) -> "Tolerance":
        """``+/- fraction * nominal``. ``0.005`` is half a percent."""
        return cls(relative=fraction)

    # -- queries --------------------------------------------------------------

    def bounds(self, nominal: float) -> tuple[float, float]:
        """The inclusive ``(low, high)`` band around ``nominal``.

        The relative part is taken against ``abs(nominal)`` so a negative
        nominal, such as a coordinate below the origin, widens the band in the
        same direction a positive one would rather than inverting it.
        """
        slack = abs(nominal) * self.relative
        return (nominal - self.minus - slack, nominal + self.plus + slack)

    def contains(self, nominal: float, actual: float) -> bool:
        low, high = self.bounds(nominal)
        return low <= actual <= high

    def deviation(self, nominal: float, actual: float) -> float:
        """Signed ``actual - nominal``. Positive means oversize."""
        return actual - nominal

    def excess(self, nominal: float, actual: float) -> float:
        """How far outside the band ``actual`` sits, signed. Zero when it passes.

        This is the number worth reporting on a failure. The deviation alone does
        not say whether it mattered; a 0.3 deviation inside a 0.5 band is fine,
        and the same deviation inside a 0.1 band is the defect.
        """
        low, high = self.bounds(nominal)
        if actual < low:
            return actual - low
        if actual > high:
            return actual - high
        return 0.0

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict[str, float]:
        """Round-trips through the shortest form that still describes the band."""
        if self.relative and not self.plus and not self.minus:
            return {"relative": self.relative}
        if self.plus == self.minus and not self.relative:
            return {"symmetric": self.plus}
        out: dict[str, float] = {}
        if self.plus:
            out["plus"] = self.plus
        if self.minus:
            out["minus"] = self.minus
        if self.relative:
            out["relative"] = self.relative
        return out

    @classmethod
    def from_value(cls, value: object, *, path: str = "tolerance") -> "Tolerance":
        """Accept a bare number as symmetric, or a mapping in any of the forms.

        A bare number is the overwhelmingly common case in a hand-written spec,
        and requiring ``{"symmetric": 0.2}`` for it would make every spec noisier
        without making any of them clearer.
        """
        if isinstance(value, bool):
            raise SpecError(f"{path}: expected a number or mapping, got a boolean")
        if isinstance(value, (int, float)):
            return cls.symmetric(float(value))
        if isinstance(value, dict):
            unknown = set(value) - {"symmetric", "plus", "minus", "relative"}
            if unknown:
                raise SpecError(
                    f"{path}: unknown key(s) {sorted(unknown)}. "
                    "Use 'symmetric', or 'plus'/'minus', or 'relative'."
                )
            if "symmetric" in value:
                if "plus" in value or "minus" in value:
                    raise SpecError(
                        f"{path}: 'symmetric' cannot be combined with 'plus'/'minus'; "
                        "they describe the same two bounds."
                    )
                return cls(
                    plus=float(value["symmetric"]),
                    minus=float(value["symmetric"]),
                    relative=float(value.get("relative", 0.0)),
                )
            return cls(
                plus=float(value.get("plus", 0.0)),
                minus=float(value.get("minus", 0.0)),
                relative=float(value.get("relative", 0.0)),
            )
        raise SpecError(f"{path}: expected a number or mapping, got {type(value).__name__}")
