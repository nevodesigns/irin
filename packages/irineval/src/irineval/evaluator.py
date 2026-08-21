"""Turning a spec into inspections, and inspection output into a verdict.

The whole file is one idea: an assertion knows what it claims, the inspection
CLI knows what is true, and this maps between them without either side learning
about the other.

Two things it takes seriously.

**Inspections are deduplicated by their exact argv, not by source.** Five
assertions about extents, part count, and face count all resolve to the same
``refs --facts`` call and pay for it once. Two interference assertions with
different volume floors are genuinely different questions and pay twice. Doing
this by source alone would either over-call or quietly answer one assertion with
another's flags.

**A failed inspection is never reported as a failed artifact.** When the CLI
errors, or a selector does not resolve, the assertion comes back undetermined
with the CLI's own message attached. A benchmark that scores its own tooling
breakage as model error produces a number that moves for the wrong reasons.
"""

from __future__ import annotations

import time
from typing import Any, Sequence

from irinspec import (
    Assertion,
    BoltCircle,
    Bounds,
    ClashCount,
    HoleCount,
    Distance,
    EdgeCount,
    FaceCount,
    NoInterference,
    PartCount,
    Size,
    Spec,
    ValidSolid,
)

from irineval.results import AssertionResult, FailureCode, SpecResult
from irineval.runner import EvalError, InspectResponse, InspectRunner

AXES = ("x", "y", "z")


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------


def inspect_argv(assertion: Assertion, entry: str) -> tuple[str, ...]:
    """The exact inspection that answers this assertion."""
    if isinstance(assertion, ValidSolid):
        argv = ["validate", entry]
        if assertion.allow_open:
            argv.append("--allow-open")
        return tuple(argv)

    if isinstance(assertion, (Size, Bounds, PartCount, FaceCount, EdgeCount)):
        return ("refs", entry, "--facts")

    if isinstance(assertion, (NoInterference, ClashCount)):
        return ("interfere", entry, "--tolerance", _number(assertion.volume_tolerance))

    if isinstance(assertion, (HoleCount, BoltCircle)):
        # Deliberately unfiltered. Every feature assertion in a spec resolves to
        # this one argv and therefore one inspection; the filtering happens in
        # Python against the full feature list. Encoding --kind or --min-diameter
        # here would split one recognition pass into several, and cylindrical
        # recognition walks every face in the solid.
        return ("features", entry)

    if isinstance(assertion, Distance):
        return (
            "measure",
            entry,
            "--from",
            assertion.from_ref,
            "--to",
            assertion.to_ref,
            "--axis",
            assertion.axis,
        )

    raise EvalError(
        f"no inspection is bound to assertion kind {assertion.kind!r}. "
        "Every kind in irinspec must map to a command here, or specs using it "
        "would parse and then never be checked."
    )


def plan(spec: Spec, entry: str) -> tuple[tuple[str, ...], ...]:
    """The deduplicated inspections a spec needs, in first-use order."""
    seen: dict[tuple[str, ...], None] = {}
    for assertion in spec.assertions:
        seen.setdefault(inspect_argv(assertion, entry), None)
    return tuple(seen)


def _number(value: float) -> str:
    """Format a float for argv without an exponent or a trailing ``.0``."""
    if value == int(value):
        return str(int(value))
    return repr(value)


# ---------------------------------------------------------------------------
# extraction helpers
# ---------------------------------------------------------------------------


def _facts(response: InspectResponse) -> tuple[dict, dict]:
    """``(summary, entryFacts)`` for the single target of a facts call."""
    tokens = response.result.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise KeyError("refs --facts returned no tokens")
    token = tokens[0]
    summary = token.get("summary")
    entry_facts = token.get("entryFacts")
    if not isinstance(summary, dict):
        raise KeyError("refs --facts returned no summary")
    return summary, entry_facts if isinstance(entry_facts, dict) else {}


def _triplet(value: object, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise KeyError(f"{label} is not three numbers")
    return (float(value[0]), float(value[1]), float(value[2]))


def _undetermined(assertion: Assertion, code: FailureCode, detail: str) -> AssertionResult:
    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=False,
        code=code,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# per-kind evaluation
# ---------------------------------------------------------------------------


def _eval_valid_solid(assertion: ValidSolid, response: InspectResponse) -> AssertionResult:
    result = response.result
    failure_count = result.get("failureCount", 0)
    parts = result.get("parts") or []
    passed = bool(result.get("ok")) and not failure_count

    detail = ""
    if not passed and parts:
        # The reasons are the actionable half. "invalidTopology" and
        # "nonPositiveVolume" point at completely different source mistakes.
        described = []
        for part in parts[:5]:
            reasons = ", ".join(part.get("reasons", []))
            described.append(f"{part.get('name') or part.get('ref')}: {reasons}")
        detail = "; ".join(described)
        if len(parts) > 5:
            detail += f"; and {len(parts) - 5} more"

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.GEOMETRY_INVALID,
        detail=detail,
        expected="every occurrence sound",
        actual=f"{failure_count} of {result.get('occurrenceCount', '?')} occurrences unsound",
    )


def _eval_scalar_band(
    assertion: Assertion,
    *,
    label: str,
    nominal: float,
    actual: float,
    tolerance: Any,
) -> tuple[bool, float, float, str]:
    """Shared band check. Returns ``(passed, deviation, excess, detail)``."""
    passed = tolerance.contains(nominal, actual)
    deviation = tolerance.deviation(nominal, actual)
    excess = tolerance.excess(nominal, actual)
    low, high = tolerance.bounds(nominal)
    detail = (
        ""
        if passed
        else f"{label}: {actual:g} is outside [{low:g}, {high:g}] by {excess:+g} mm"
    )
    return passed, deviation, excess, detail


def _eval_size(assertion: Size, response: InspectResponse) -> AssertionResult:
    _summary, entry_facts = _facts(response)
    measured = _triplet(entry_facts.get("size"), "entryFacts.size")
    by_axis = dict(zip(AXES, measured))

    failures: list[str] = []
    worst_excess = 0.0
    worst_deviation = 0.0
    for axis, nominal in assertion.axes().items():
        actual = by_axis[axis]
        passed, deviation, excess, detail = _eval_scalar_band(
            assertion, label=axis, nominal=nominal, actual=actual, tolerance=assertion.tolerance
        )
        if not passed:
            failures.append(detail)
            # Report the axis that misses by the most; it is the one to chase.
            if abs(excess) > abs(worst_excess):
                worst_excess, worst_deviation = excess, deviation

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=not failures,
        code=None if not failures else FailureCode.DIMENSION_OUT_OF_TOLERANCE,
        detail="; ".join(failures),
        expected=assertion.axes(),
        actual={a: by_axis[a] for a in assertion.axes()},
        deviation=worst_deviation if failures else 0.0,
        excess=worst_excess if failures else 0.0,
    )


def _eval_bounds(assertion: Bounds, response: InspectResponse) -> AssertionResult:
    summary, _facts_unused = _facts(response)
    bounds = summary.get("bounds")
    if not isinstance(bounds, dict):
        raise KeyError("refs --facts returned no bounds")

    measured = {
        "min": _triplet(bounds.get("min"), "bounds.min"),
        "max": _triplet(bounds.get("max"), "bounds.max"),
    }

    failures: list[str] = []
    worst_excess = 0.0
    worst_deviation = 0.0
    expected: dict[str, list[float]] = {}
    actual: dict[str, list[float]] = {}

    for corner in ("min", "max"):
        wanted = getattr(assertion, corner)
        if wanted is None:
            continue
        expected[corner] = list(wanted)
        actual[corner] = list(measured[corner])
        for index, axis in enumerate(AXES):
            passed, deviation, excess, detail = _eval_scalar_band(
                assertion,
                label=f"{corner}.{axis}",
                nominal=wanted[index],
                actual=measured[corner][index],
                tolerance=assertion.tolerance,
            )
            if not passed:
                failures.append(detail)
                if abs(excess) > abs(worst_excess):
                    worst_excess, worst_deviation = excess, deviation

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=not failures,
        code=None if not failures else FailureCode.DIMENSION_OUT_OF_TOLERANCE,
        detail="; ".join(failures),
        expected=expected,
        actual=actual,
        deviation=worst_deviation if failures else 0.0,
        excess=worst_excess if failures else 0.0,
    )


_COUNT_FIELDS = {
    "part_count": "leafOccurrenceCount",
    "face_count": "faceCount",
    "edge_count": "edgeCount",
}


def _eval_count(assertion: Assertion, response: InspectResponse) -> AssertionResult:
    summary, _ = _facts(response)
    field = _COUNT_FIELDS[assertion.kind]
    if field not in summary:
        raise KeyError(f"refs --facts returned no {field}")
    actual = int(summary[field])
    expected = int(assertion.value)  # type: ignore[attr-defined]
    passed = actual == expected

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.COUNT_MISMATCH,
        detail="" if passed else f"expected {expected}, found {actual}",
        expected=expected,
        actual=actual,
        deviation=float(actual - expected),
    )


def _eval_no_interference(assertion: NoInterference, response: InspectResponse) -> AssertionResult:
    result = response.result
    clash_count = int(result.get("clashCount", 0))
    passed = clash_count == 0

    detail = ""
    if not passed:
        described = []
        for clash in (result.get("clashes") or [])[:5]:
            a = (clash.get("a") or {}).get("name") or (clash.get("a") or {}).get("ref")
            b = (clash.get("b") or {}).get("name") or (clash.get("b") or {}).get("ref")
            described.append(f"{a} into {b} by {clash.get('volume')} mm^3")
        detail = "; ".join(described)
        if clash_count > 5:
            detail += f"; and {clash_count - 5} more"

    stats = result.get("stats") or {}
    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.INTERFERENCE,
        detail=detail,
        expected=0,
        actual=clash_count,
        deviation=float(clash_count),
    )


def _eval_distance(assertion: Distance, response: InspectResponse) -> AssertionResult:
    measurement = response.result.get("measurement")
    if not isinstance(measurement, dict) or "absoluteDistance" not in measurement:
        raise KeyError("measure returned no absoluteDistance")
    # Magnitude along the axis. Direction is deliberately not asserted: the
    # schema has no way to say which way round the refs were meant, so checking
    # the signed value would fail correct models on ref ordering alone.
    actual = float(measurement["absoluteDistance"])
    passed, deviation, excess, detail = _eval_scalar_band(
        assertion,
        label=f"{assertion.from_ref} to {assertion.to_ref} along {assertion.axis}",
        nominal=assertion.value,
        actual=actual,
        tolerance=assertion.tolerance,
    )
    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.DIMENSION_OUT_OF_TOLERANCE,
        detail=detail,
        expected=assertion.value,
        actual=actual,
        deviation=deviation,
        excess=excess,
    )


def _eval_clash_count(assertion: ClashCount, response: InspectResponse) -> AssertionResult:
    result = response.result
    actual = int(result.get("clashCount", 0))
    expected = int(assertion.value)
    passed = actual == expected

    detail = ""
    if not passed:
        described = []
        for clash in (result.get("clashes") or [])[:3]:
            a = (clash.get("a") or {}).get("name") or (clash.get("a") or {}).get("ref")
            b = (clash.get("b") or {}).get("name") or (clash.get("b") or {}).get("ref")
            described.append(f"{a} into {b} by {clash.get('volume')} mm^3")
        detail = f"expected {expected}, found {actual}"
        if described:
            detail += ": " + "; ".join(described)

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.COUNT_MISMATCH,
        detail=detail,
        expected=expected,
        actual=actual,
        deviation=float(actual - expected),
    )


def _matching_holes(assertion: HoleCount, response: InspectResponse) -> list[dict[str, Any]]:
    holes = [
        feature
        for feature in (response.result.get("features") or [])
        if feature.get("kind") == "hole"
    ]
    if assertion.through is not None:
        holes = [hole for hole in holes if bool(hole.get("through")) is assertion.through]
    if assertion.diameter is not None:
        holes = [
            hole
            for hole in holes
            if assertion.tolerance.contains(assertion.diameter, float(hole.get("diameter", 0.0)))
        ]
    return holes


def _eval_hole_count(assertion: HoleCount, response: InspectResponse) -> AssertionResult:
    matching = _matching_holes(assertion, response)
    actual = len(matching)
    expected = int(assertion.value)
    passed = actual == expected

    detail = ""
    if not passed:
        detail = f"expected {expected}, found {actual}"
        # Naming what IS there turns "found 0" into a number to change, which is
        # the difference between a failure and a fix. Reported whether or not a
        # diameter filter was given: a part with no holes at all is worth saying
        # plainly either way.
        present = sorted(
            {
                round(float(f.get("diameter", 0.0)), 3)
                for f in (response.result.get("features") or [])
                if f.get("kind") == "hole"
            }
        )
        if not present:
            detail += "; the part has no holes at all"
        elif assertion.diameter is not None and actual == 0:
            detail += f"; hole diameters present: {present}"

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.COUNT_MISMATCH,
        detail=detail,
        expected=expected,
        actual=actual,
        deviation=float(actual - expected),
    )


def _eval_bolt_circle(assertion: BoltCircle, response: InspectResponse) -> AssertionResult:
    patterns = response.result.get("patterns") or []

    def matches(pattern: dict[str, Any]) -> bool:
        if not pattern.get("uniform"):
            return False
        if int(pattern.get("count", 0)) != assertion.count:
            return False
        if not assertion.tolerance.contains(
            assertion.diameter, float(pattern.get("circleDiameter", 0.0))
        ):
            return False
        if assertion.hole_diameter is not None and not assertion.hole_tolerance.contains(
            assertion.hole_diameter, float(pattern.get("holeDiameter", 0.0))
        ):
            return False
        return True

    found = next((pattern for pattern in patterns if matches(pattern)), None)
    passed = found is not None

    detail = ""
    actual: Any = None
    if passed:
        actual = round(float(found.get("circleDiameter", 0.0)), 4)
    else:
        # Say which part of the claim failed. A bolt circle is three facts at
        # once, and "no match" alone leaves the reader to guess which.
        if not patterns:
            detail = "no circular hole pattern found"
        else:
            described = []
            for pattern in patterns[:4]:
                shape = "uniform" if pattern.get("uniform") else "not evenly spaced"
                described.append(
                    f"{pattern.get('count')} x d={pattern.get('holeDiameter')} on "
                    f"{pattern.get('circleDiameter')} mm ({shape})"
                )
            detail = "found instead: " + "; ".join(described)

    return AssertionResult(
        kind=assertion.kind,
        description=assertion.describe(),
        passed=passed,
        code=None if passed else FailureCode.COUNT_MISMATCH,
        detail=detail,
        expected=assertion.diameter,
        actual=actual,
    )


_EVALUATORS = {
    "valid_solid": _eval_valid_solid,
    "size": _eval_size,
    "bounds": _eval_bounds,
    "part_count": _eval_count,
    "face_count": _eval_count,
    "edge_count": _eval_count,
    "no_interference": _eval_no_interference,
    "clash_count": _eval_clash_count,
    "hole_count": _eval_hole_count,
    "bolt_circle": _eval_bolt_circle,
    "distance": _eval_distance,
}


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


def _selector_problem(response: InspectResponse) -> bool:
    """Does this failure mean a ref did not resolve, rather than a broken run?

    A ref that does not resolve usually means the model came out differently
    than the spec assumed, which is worth reporting as its own state rather than
    as generic tooling breakage.
    """
    return any("did not resolve" in message for message in response.error_messages())


def evaluate(
    spec: Spec,
    entry: str,
    runner: InspectRunner,
) -> SpecResult:
    """Check every assertion in ``spec`` against the artifact at ``entry``."""
    started = time.monotonic()

    responses: dict[tuple[str, ...], InspectResponse] = {}
    for argv in plan(spec, entry):
        try:
            responses[argv] = runner.run(argv)
        except EvalError as exc:
            # Record the failure against the argv so every assertion depending on
            # it reports the same cause, instead of the first one swallowing it.
            responses[argv] = InspectResponse(
                ok=False, exit_code=1, result={"errors": [{"message": str(exc)}]}
            )

    results: list[AssertionResult] = []
    for assertion in spec.assertions:
        argv = inspect_argv(assertion, entry)
        response = responses[argv]

        # `ok: false` alone does NOT mean the inspection broke. Both `validate`
        # and `interfere` set it false for a legitimately defective artifact and
        # exit 2, with `errors` empty. Treating that as tooling breakage would
        # report every real geometry defect as undetermined and hide precisely
        # what this evaluator exists to catch.
        #
        # `errors` is the discriminator: populated means the command could not
        # answer the question, empty means it answered and the answer is bad.
        if response.error_messages():
            code = (
                FailureCode.SELECTOR_UNRESOLVED
                if _selector_problem(response)
                else FailureCode.INSPECTION_FAILED
            )
            results.append(_undetermined(assertion, code, response.first_error()))
            continue

        try:
            results.append(_EVALUATORS[assertion.kind](assertion, response))
        except (KeyError, TypeError, ValueError) as exc:
            # The command succeeded but its payload was not the shape this
            # evaluator binds to. That is a version skew between IRIN and the
            # CAD CLI, not a defect in the model, so it stays undetermined.
            results.append(
                _undetermined(
                    assertion,
                    FailureCode.INSPECTION_FAILED,
                    f"unexpected inspect output: {exc}",
                )
            )

    return SpecResult(
        spec_id=spec.id,
        entry=entry,
        results=tuple(results),
        inspections=tuple(" ".join(argv) for argv in responses),
        duration_s=time.monotonic() - started,
    )


def measured_facts(runner: InspectRunner, entry: str) -> dict[str, Any]:
    """The geometry facts of an artifact, normalized.

    Public so that anything building a spec from an existing model reads the
    inspection payload through the same code the evaluator checks against. Two
    separate readings of the same JSON would drift apart, and a corpus derived
    against one shape while scored against another produces failures nobody can
    explain.

    Raises ``EvalError`` when the facts cannot be established, because a caller
    deriving a baseline needs to stop rather than record a guess.
    """
    response = runner.run(("refs", entry, "--facts"))
    if response.error_messages():
        raise EvalError(f"cannot read facts for {entry}: {response.first_error()}")
    try:
        summary, entry_facts = _facts(response)
        bounds = summary["bounds"]
        return {
            "size": _triplet(entry_facts.get("size"), "entryFacts.size"),
            "bounds": {
                "min": _triplet(bounds.get("min"), "bounds.min"),
                "max": _triplet(bounds.get("max"), "bounds.max"),
            },
            "part_count": int(summary["leafOccurrenceCount"]),
            "face_count": int(summary["faceCount"]),
            "edge_count": int(summary["edgeCount"]),
            "kind": summary.get("kind", ""),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalError(f"unexpected facts payload for {entry}: {exc}") from exc


def measured_clashes(runner: InspectRunner, entry: str, *, volume_tolerance: float = 1.0) -> int:
    """How many part-vs-part overlaps an artifact has at this volume floor.

    Separate from ``measured_facts`` because it is by far the most expensive
    inspection: a pairwise boolean over every candidate pair. A caller deriving a
    baseline should reach for it deliberately, not get it for free alongside the
    cheap topology counts.
    """
    response = runner.run(("interfere", entry, "--tolerance", _number(volume_tolerance)))
    if response.error_messages():
        raise EvalError(f"cannot read interference for {entry}: {response.first_error()}")
    try:
        return int(response.result["clashCount"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalError(f"unexpected interference payload for {entry}: {exc}") from exc


def evaluate_all(
    specs: Sequence[Spec],
    entry_for: Any,
    runner: InspectRunner,
) -> tuple[SpecResult, ...]:
    """Evaluate several specs with one runner.

    ``entry_for`` maps a spec to its artifact path: either a callable taking the
    spec, or a mapping keyed by spec id. Sharing the runner is the point, since
    the worker process and its OpenCascade import are then paid for once across
    the whole set rather than once per spec.
    """

    def resolve(spec: Spec) -> str:
        if callable(entry_for):
            return entry_for(spec)
        return entry_for[spec.id]

    return tuple(evaluate(spec, resolve(spec), runner) for spec in specs)
