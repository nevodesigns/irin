"""Running a corpus and recording what happened.

One worker serves the whole run, so the CAD kernel is imported once rather than
once per model. On fifty models that is the difference between a run you wait
for and one you schedule.

A result file records the version it ran against and the corpus it ran, because
a score with no provenance cannot be compared to anything. "84%" means nothing
without knowing which fifty models, at which tolerance, on which release.
"""

from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from irineval import InspectRunner, SpecResult, evaluate

from irinbench.corpus import Corpus


@dataclass
class RunResult:
    """Every spec in a corpus, evaluated."""

    corpus_name: str
    corpus_kind: str
    results: tuple[SpecResult, ...]
    started_at: str = ""
    duration_s: float = 0.0
    environment: dict[str, Any] = field(default_factory=dict)

    # -- aggregates -----------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passing(self) -> int:
        """Specs where every assertion was checked and held."""
        return sum(1 for r in self.results if r.ok)

    @property
    def with_defects(self) -> int:
        return sum(1 for r in self.results if r.defect_count)

    @property
    def with_undetermined(self) -> int:
        """Specs where at least one assertion could not be established.

        Counted separately from defects everywhere. A run with twenty of these
        has a tooling problem, not a geometry problem, and treating them the
        same would send someone hunting the wrong bug.
        """
        return sum(1 for r in self.results if r.undetermined_count)

    @property
    def assertions_total(self) -> int:
        return sum(r.total for r in self.results)

    @property
    def assertions_passed(self) -> int:
        return sum(r.passed_count for r in self.results)

    @property
    def assertions_undetermined(self) -> int:
        return sum(r.undetermined_count for r in self.results)

    @property
    def spec_pass_rate(self) -> float:
        return self.passing / self.total if self.total else 0.0

    @property
    def assertion_pass_rate(self) -> float:
        return self.assertions_passed / self.assertions_total if self.assertions_total else 0.0

    def failures(self) -> tuple[SpecResult, ...]:
        return tuple(r for r in self.results if not r.ok)

    # -- persistence ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": {"name": self.corpus_name, "kind": self.corpus_kind},
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 3),
            "environment": self.environment,
            "totals": {
                "specs": self.total,
                "specs_passing": self.passing,
                "specs_with_defects": self.with_defects,
                "specs_with_undetermined": self.with_undetermined,
                "assertions": self.assertions_total,
                "assertions_passed": self.assertions_passed,
                "assertions_undetermined": self.assertions_undetermined,
            },
            "rates": {
                "spec_pass_rate": round(self.spec_pass_rate, 6),
                "assertion_pass_rate": round(self.assertion_pass_rate, 6),
            },
            "results": [r.to_dict() for r in self.results],
        }

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return p


def _environment(repo_root: Path) -> dict[str, Any]:
    version_file = repo_root / "VERSION"
    return {
        "irin_version": version_file.read_text(encoding="utf-8").strip()
        if version_file.exists()
        else "unknown",
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def run_corpus(
    corpus: Corpus,
    runner: InspectRunner,
    *,
    repo_root: str | Path = ".",
    on_result: Callable[[SpecResult], None] | None = None,
) -> RunResult:
    """Evaluate every spec in a corpus against its bound artifact."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    results: list[SpecResult] = []
    for spec in corpus.specs:
        result = evaluate(spec, corpus.entry_for(spec), runner)
        results.append(result)
        if on_result:
            on_result(result)

    return RunResult(
        corpus_name=corpus.name,
        corpus_kind=corpus.kind,
        results=tuple(results),
        started_at=started_at,
        duration_s=time.monotonic() - started,
        environment=_environment(Path(repo_root)),
    )
