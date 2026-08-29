"""Check a stored result for signs that the harness produced it, not the model.

Every scoring bug this repository has shipped was found the same way: somebody
looked at a number, thought it seemed low, and went digging. That is not a
detection mechanism. It depends on the number being surprising, and the most
dangerous failure is the one that lands somewhere plausible.

The local 3B model scored 0/28 through a bug that fabricated all 149 of its
failure reasons, and 0/28 is exactly what a 3B model scoring honestly would have
got. Nothing about that result looked wrong. It was found only because a
different model was poisoned by the same bug into a number that did look wrong.

So the checks here are deliberately not about whether a score is good. They ask
a narrower question with a checkable answer: **does this result look like it was
produced by measuring twenty-eight different things?** A harness that breaks
tends to break identically everywhere, and that leaves a signature in the shape
of the failures even when the totals are unremarkable.

Every finding is a suspicion, not a verdict. A model really can fail every task
the same way, and a run really can be legitimately partial. The output says what
looks wrong and what would confirm it, and the caller decides.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

__all__ = ["Finding", "audit_result", "format_audit", "load_result"]

#: Below this many failing assertions, agreement means nothing. Three failures
#: sharing a reason is a small model being consistent, not a harness stuck.
_MIN_FAILURES = 12

#: A harness that fails once and reports it everywhere leaves near-total
#: agreement. A model failing honestly spreads its mistakes out.
_UNIFORM_DETAIL_RATIO = 0.6

#: How many distinct reasons a genuine run tends to produce, as a fraction of
#: the specs that failed. Well under one reason per four specs is worth a look.
_MIN_DISTINCT_RATIO = 0.25


@dataclass(frozen=True)
class Finding:
    """One thing about a result that suggests it was not really measured."""

    code: str
    detail: str
    #: What would settle it, stated as an action rather than a feeling.
    confirm: str

    def format(self) -> str:
        return f"  {self.code}\n    {self.detail}\n    confirm: {self.confirm}"


def audit_result(data: dict[str, Any]) -> tuple[Finding, ...]:
    """Return what looks wrong about ``data``, or an empty tuple."""
    results = data.get("results") or []
    if not results:
        return (
            Finding(
                "empty",
                "the file records no per-spec results, so nothing in it can be checked",
                "re-run the corpus and keep the result the run writes",
            ),
        )

    findings: list[Finding] = []
    findings.extend(_check_uniform_failure_reason(results))
    findings.extend(_check_reason_diversity(results))
    findings.extend(_check_unmarked_partial(data, results))
    return tuple(findings)


def _failing_details(results: Iterable[dict[str, Any]]) -> list[str]:
    details: list[str] = []
    for result in results:
        for assertion in result.get("assertions") or []:
            if assertion.get("passed"):
                continue
            details.append(str(assertion.get("detail") or ""))
    return details


def _check_uniform_failure_reason(results: list[dict[str, Any]]) -> list[Finding]:
    """Did one failure get reported as every failure?

    This is the poisoning signature exactly. A single unreadable file aborted
    the directory walk, so every assertion in the submission came back carrying
    that one file's error, and two published results were scored that way.
    """
    details = _failing_details(results)
    if len(details) < _MIN_FAILURES:
        return []

    counts = Counter(d for d in details if d)
    if not counts:
        return []

    reason, hits = counts.most_common(1)[0]
    ratio = hits / len(details)
    if ratio < _UNIFORM_DETAIL_RATIO:
        return []

    excerpt = reason if len(reason) <= 70 else reason[:67] + "..."
    return [
        Finding(
            "uniform-failure-reason",
            f"{hits} of {len(details)} failing assertions ({ratio:.0%}) give the same "
            f"reason: {excerpt!r}. One fault reported everywhere looks like this, and "
            "so does a harness that stopped measuring after the first problem.",
            "open the artifact that reason names. If nothing is wrong with the other "
            "artifacts, the run measured one file and attributed it to all of them",
        )
    ]


def _check_reason_diversity(results: list[dict[str, Any]]) -> list[Finding]:
    """Did the run produce as many distinct reasons as it scored failing specs?

    Weaker than the uniformity check and catches a different case: a handful of
    harness faults rather than one, which spreads across several reasons and
    stays under the uniformity threshold while still measuring almost nothing.
    """
    details = [d for d in _failing_details(results) if d]
    if len(details) < _MIN_FAILURES:
        return []

    failing_specs = sum(1 for r in results if not r.get("ok"))
    if failing_specs == 0:
        return []

    distinct = len(set(details))
    if distinct / failing_specs >= _MIN_DISTINCT_RATIO:
        return []

    return [
        Finding(
            "few-distinct-reasons",
            f"{failing_specs} specs failed but they give only {distinct} distinct "
            "reasons between them. Independent attempts at different requirements "
            "usually fail in more ways than that.",
            "list the distinct reasons. If they name files or paths rather than "
            "geometry or API misuse, the harness is failing, not the agent",
        )
    ]


def _check_unmarked_partial(
    data: dict[str, Any], results: list[dict[str, Any]]
) -> list[Finding]:
    """Does the result score fewer specs than the corpus holds, without saying so?

    A run scored over a subset is a smaller and differently chosen sample, and a
    percentage over it is not comparable to a full pass. ``partial`` is what says
    so, and a result missing the flag reads as complete.
    """
    corpus = data.get("corpus") or {}
    held = corpus.get("tasks")
    scored = len(results)
    if not isinstance(held, int) or held <= 0 or scored >= held:
        return []
    if data.get("partial"):
        return []

    return [
        Finding(
            "unmarked-partial",
            f"{scored} of {held} tasks were scored, but the result is not marked "
            "partial, so it reads as a complete run that went badly.",
            "re-run with --only naming the tasks actually attempted, which marks "
            "the result partial and records the corpus size",
        )
    ]


def format_audit(path: Path, findings: tuple[Finding, ...]) -> str:
    """Render an audit for a terminal."""
    lines = [f"audit: {path.name}"]
    if not findings:
        lines.append("  nothing suspicious about the shape of this result")
        lines.append("")
        lines.append("  This is not a claim that the number is right. It means the")
        lines.append("  failures vary the way independent attempts vary, so the run")
        lines.append("  does not carry the signature of a harness that broke once")
        lines.append("  and reported it everywhere.")
        return "\n".join(lines)

    lines.append("")
    for finding in findings:
        lines.append(finding.format())
        lines.append("")
    lines.append("  A finding is a suspicion, not a verdict. A model can genuinely")
    lines.append("  fail every task the same way. Confirm before discarding a number,")
    lines.append("  and confirm before publishing one.")
    return "\n".join(lines)


def load_result(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is valid JSON but not a result object")
    return data
