"""What an evaluation produced: per assertion, and for the spec as a whole.

Two rules shape everything here.

**A result records what was measured, not only whether it passed.** A bare
false tells you nothing you can act on. The actual value, the expected value,
and how far outside the band it landed are what turn a failure into a parameter
to change.

**A check that could not run is not a check that failed.** An inspection that
crashed, a selector that did not resolve, and a dimension that is genuinely
0.4 mm oversize are three different situations. Collapsing them into one boolean
produces a benchmark that reports tooling breakage as model error, which is the
fastest way to make a number meaningless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureCode(str, Enum):
    """Why an assertion did not pass.

    A string enum so it serializes to something readable in a result file
    without a custom encoder, and groups cleanly in a report.
    """

    GEOMETRY_INVALID = "geometry_invalid"

    #: The source exists but does not produce geometry: it raised, or the kernel
    #: refused what it built. A defect, not an unknown. The agent shipped
    #: something that does not run, which is a failure of the artifact and not of
    #: the tooling asked to measure it.
    ARTIFACT_BROKEN = "artifact_broken"
    DIMENSION_OUT_OF_TOLERANCE = "dimension_out_of_tolerance"
    COUNT_MISMATCH = "count_mismatch"
    INTERFERENCE = "interference"

    #: The task produced no artifact at all. A defect rather than undetermined,
    #: deliberately: an agent given a prompt and returning nothing has failed,
    #: and scoring that as inconclusive would let the worst possible outcome
    #: report as the mildest one.
    ARTIFACT_MISSING = "artifact_missing"

    # The two below mean IRIN could not establish the answer. They are kept
    # apart from the four above everywhere they are counted.
    INSPECTION_FAILED = "inspection_failed"
    SELECTOR_UNRESOLVED = "selector_unresolved"


#: Codes that mean the artifact is wrong.
DEFECT_CODES = frozenset(
    {
        FailureCode.GEOMETRY_INVALID,
        FailureCode.ARTIFACT_BROKEN,
        FailureCode.DIMENSION_OUT_OF_TOLERANCE,
        FailureCode.COUNT_MISMATCH,
        FailureCode.INTERFERENCE,
        FailureCode.ARTIFACT_MISSING,
    }
)

#: Codes that mean IRIN could not tell. Never counted as a model failure.
UNDETERMINED_CODES = frozenset(
    {
        FailureCode.INSPECTION_FAILED,
        FailureCode.SELECTOR_UNRESOLVED,
    }
)


_ADDRESS = re.compile(r"0x[0-9a-fA-F]{6,}")


def _stable_detail(detail: str) -> str:
    """Strip the parts of an error message that change between identical runs.

    OCP renders its C++ objects with their memory address, so a failure detail
    reads ``<OCP.gp_Trsf object at 0x7d9df072fbf0>``. The address is different on
    every run of the same code against the same model, which means two results
    that agree on every measurement still differ byte for byte.

    That matters more than it sounds. A stored result is meant to be diffable: an
    author re-scoring a submission wants the diff to show what changed about the
    answer, and a diff full of addresses hides a real change inside noise. It
    also breaks the claim the regression corpus rests on, that re-deriving an
    unchanged model reproduces its baseline exactly.

    The address carries no information for the reader. The type and the call that
    failed carry all of it, and both survive.
    """
    return _ADDRESS.sub("0x...", detail)


@dataclass(frozen=True)
class AssertionResult:
    """One assertion, checked."""

    kind: str
    description: str
    passed: bool
    code: FailureCode | None = None
    detail: str = ""
    expected: Any = None
    actual: Any = None
    #: Signed ``actual - expected`` where both are scalar.
    deviation: float | None = None
    #: Signed distance outside the tolerance band. Zero when inside it.
    excess: float | None = None

    def __post_init__(self) -> None:
        if self.detail:
            object.__setattr__(self, "detail", _stable_detail(self.detail))

    @property
    def undetermined(self) -> bool:
        return self.code in UNDETERMINED_CODES

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "description": self.description,
            "passed": self.passed,
        }
        if self.code is not None:
            out["code"] = self.code.value
        if self.detail:
            out["detail"] = self.detail
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        if self.deviation is not None:
            out["deviation"] = self.deviation
        if self.excess is not None:
            out["excess"] = self.excess
        return out


@dataclass(frozen=True)
class SpecResult:
    """One spec, evaluated against one artifact."""

    spec_id: str
    entry: str
    results: tuple[AssertionResult, ...]
    inspections: tuple[str, ...] = ()
    duration_s: float | None = None

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def defect_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and not r.undetermined)

    @property
    def undetermined_count(self) -> int:
        return sum(1 for r in self.results if r.undetermined)

    @property
    def ok(self) -> bool:
        """True only when every assertion was checked and every one passed.

        An undetermined assertion is not a pass. Reporting it as one would let a
        broken inspection produce a green spec, which is precisely the failure
        this project exists to stop.
        """
        return self.total > 0 and self.passed_count == self.total

    @property
    def score(self) -> float:
        """Fraction of assertions that passed, undetermined ones counted against.

        Deliberately unweighted. A weighted score needs a defensible weighting,
        and inventing one would dress a guess up as a measurement.
        """
        if not self.total:
            return 0.0
        return self.passed_count / self.total

    def failures(self) -> tuple[AssertionResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "spec": self.spec_id,
            "entry": self.entry,
            "ok": self.ok,
            "score": round(self.score, 6),
            "counts": {
                "total": self.total,
                "passed": self.passed_count,
                "defects": self.defect_count,
                "undetermined": self.undetermined_count,
            },
            "inspections": list(self.inspections),
            "assertions": [r.to_dict() for r in self.results],
        }
        if self.duration_s is not None:
            out["duration_s"] = round(self.duration_s, 4)
        return out

    def summary_line(self) -> str:
        state = "PASS" if self.ok else "FAIL"
        bits = f"{self.passed_count}/{self.total}"
        if self.undetermined_count:
            bits += f", {self.undetermined_count} undetermined"
        return f"{state}  {self.spec_id}  ({bits})"
