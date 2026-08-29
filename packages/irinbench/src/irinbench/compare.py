"""Putting results side by side, and refusing to do so when that would mislead.

One result is a measurement. Several results are a benchmark, but only if they
were scored against the same requirements. Two runs of "the tasks corpus" taken
a month apart can describe entirely different sets of tasks, and a table that
lined them up anyway would manufacture a comparison that does not exist.

So this groups by corpus fingerprint and compares only within a group. A result
with no fingerprint predates the mechanism and is listed apart, unquotable,
rather than quietly folded in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class StoredResult:
    """One result file, read for comparison rather than re-scored."""

    path: Path
    corpus_name: str
    corpus_kind: str
    fingerprint: str
    agent: str
    started_at: str
    specs: int
    specs_passing: int
    assertions: int
    assertions_passed: int
    assertions_undetermined: int
    irin_version: str
    corpus_tasks: int = 0
    partial: bool = False

    @property
    def spec_rate(self) -> float:
        return self.specs_passing / self.specs if self.specs else 0.0

    @property
    def assertion_rate(self) -> float:
        return self.assertions_passed / self.assertions if self.assertions else 0.0

    @property
    def label(self) -> str:
        name = self.agent or self.path.stem
        return f"{name} (partial)" if self.partial else name

    @classmethod
    def load(cls, path: str | Path) -> "StoredResult":
        p = Path(path)
        data: Any = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            # Valid JSON that is not a result. A results directory collects
            # unrelated files, and a list parses cleanly then fails on the first
            # attribute access, which reads as a crash rather than a skip.
            raise ValueError(f"{p} is valid JSON but not a result object")
        corpus = data.get("corpus", {})
        if not isinstance(corpus, dict):
            raise ValueError(f"{p} has no corpus block")
        totals = data.get("totals", {})
        return cls(
            path=p,
            corpus_name=corpus.get("name", "?"),
            corpus_kind=corpus.get("kind", "?"),
            fingerprint=corpus.get("fingerprint", ""),
            agent=str(data.get("agent", "")),
            started_at=data.get("started_at", ""),
            specs=int(totals.get("specs", 0)),
            specs_passing=int(totals.get("specs_passing", 0)),
            assertions=int(totals.get("assertions", 0)),
            assertions_passed=int(totals.get("assertions_passed", 0)),
            assertions_undetermined=int(totals.get("assertions_undetermined", 0)),
            irin_version=data.get("environment", {}).get("irin_version", "?"),
            corpus_tasks=int(corpus.get("tasks", 0)),
            partial=bool(data.get("partial", False)),
        )


def load_results(paths: Iterable[str | Path]) -> tuple[StoredResult, ...]:
    out = []
    for path in paths:
        try:
            out.append(StoredResult.load(path))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # A directory of results will collect unrelated JSON over time.
            # Skipping what does not parse beats refusing to compare anything.
            continue
    return tuple(out)


def group_by_corpus(results: Iterable[StoredResult]) -> dict[str, list[StoredResult]]:
    """Comparable sets. The key is the fingerprint, not the corpus name."""
    groups: dict[str, list[StoredResult]] = {}
    for result in results:
        groups.setdefault(result.fingerprint, []).append(result)
    for items in groups.values():
        items.sort(key=lambda r: (-r.spec_rate, r.label))
    return groups


def format_comparison(results: Iterable[StoredResult]) -> str:
    results = list(results)
    if not results:
        return "  no results to compare"

    groups = group_by_corpus(results)
    lines: list[str] = []

    unquotable = groups.pop("", None)

    for fingerprint, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        head = items[0]
        lines.append(f"corpus {head.corpus_name} ({head.corpus_kind})  {fingerprint[:12]}")
        # The corpus size, not the first result's attempted count. Results are
        # sorted best first, so a partial run that scored well sat at the head
        # and made the group announce "21 task(s) each" for a corpus of 28,
        # which was wrong about every row including its own.
        size = max((r.corpus_tasks for r in items), default=0) or head.specs
        counts = {r.specs for r in items}
        suffix = " each" if len(counts) == 1 else ""
        lines.append(f"  {len(items)} result(s), {size} task(s) in the corpus{suffix}")
        lines.append("")
        width = max(len(r.label) for r in items)
        lines.append(
            f"  {'agent':<{width}}   {'specs':>11}  {'':<6}  {'assertions':>11}  {'':<6}  undet"
        )
        for r in items:
            lines.append(
                f"  {r.label:<{width}}   "
                f"{r.specs_passing:>4} / {r.specs:<4}  {r.spec_rate * 100:5.1f}%  "
                f"{r.assertions_passed:>4} / {r.assertions:<4}  {r.assertion_rate * 100:5.1f}%  "
                f"{r.assertions_undetermined:>5}"
            )
        lines.append("")

    if len(groups) > 1:
        lines.append(
            "  These groups are NOT comparable to each other: each was scored against"
        )
        lines.append("  a different set of requirements.")
        lines.append("")

    if unquotable:
        lines.append("not comparable, no corpus fingerprint recorded:")
        for r in unquotable:
            lines.append(f"  {r.path.name}  ({r.label})")
        lines.append("")
        lines.append("  These predate corpus fingerprints. The numbers in them are real,")
        lines.append("  but nothing records which requirements produced them.")

    return "\n".join(lines).rstrip()
