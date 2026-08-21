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

from irineval import AssertionResult, FailureCode, InspectRunner, SpecResult, evaluate

from irinbench.corpus import KIND_TASK, Corpus, CorpusError


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
    def missing_artifacts(self) -> int:
        """Tasks that produced nothing at all.

        Reported on its own line rather than folded into the failure count. An
        agent that builds forty of fifty parts badly and one that builds none at
        all are different results, and a single percentage cannot tell them
        apart.
        """
        return sum(
            1
            for result in self.results
            if result.results
            and all(a.code == FailureCode.ARTIFACT_MISSING for a in result.results)
        )

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
                "missing_artifacts": self.missing_artifacts,
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


ARTIFACT_SUFFIXES = (".step.py", ".step", ".stp")


def resolve_artifact(artifacts_dir: str | Path, spec_id: str) -> str | None:
    """What an agent produced for one task, named relative to its directory.

    ``<spec-id>.step.py`` first, then ``.step`` and ``.stp``. A generator is
    preferred over an exported STEP because it is what a repair loop would later
    have to edit; the exported file is derived from it.

    The name is returned RELATIVE, not absolute, and that is load bearing. The
    CAD CLI refuses an absolute target outside its working directory, so a
    submission directory anywhere other than inside the repository would come
    back undetermined for every task. Relative names plus a runner rooted at the
    submission directory is the combination that works, and the two are checked
    against each other below.
    """
    directory = Path(artifacts_dir)
    for suffix in ARTIFACT_SUFFIXES:
        if (directory / f"{spec_id}{suffix}").exists():
            return f"{spec_id}{suffix}"
    return None


def _missing_artifact_result(spec, expected: str) -> SpecResult:
    """Every assertion fails as ARTIFACT_MISSING, none as undetermined.

    Undetermined would be the wrong verdict. It means IRIN could not establish
    the answer, and here the answer is established: nothing was produced.
    """
    return SpecResult(
        spec_id=spec.id,
        entry=expected,
        results=tuple(
            AssertionResult(
                kind=assertion.kind,
                description=assertion.describe(),
                passed=False,
                code=FailureCode.ARTIFACT_MISSING,
                detail=f"no artifact for this task; looked for {expected}",
            )
            for assertion in spec.assertions
        ),
    )


def run_task_corpus(
    corpus: Corpus,
    artifacts_dir: str | Path,
    runner: InspectRunner,
    *,
    repo_root: str | Path = ".",
    on_result: Callable[[SpecResult], None] | None = None,
) -> RunResult:
    """Score what an agent produced for each task in a task corpus.

    ``artifacts_dir`` is required and has no default. A task corpus holds
    reference implementations, and defaulting to those would score the answer
    key: every task would pass and the run would report a perfect result that
    measured nothing.
    """
    if corpus.kind != KIND_TASK:
        raise CorpusError(
            f"{corpus.name!r} is a {corpus.kind} corpus. Its specs are bound to "
            "their own models, so use run_corpus."
        )

    # Artifacts are named relative to their own directory, so a runner rooted
    # anywhere else resolves every one of them against the wrong place and the
    # whole submission scores as undetermined. Caught here rather than discovered
    # from a report of seventeen identical inspection failures.
    runner_cwd = getattr(runner, "cwd", None)
    if runner_cwd is not None and Path(runner_cwd).resolve() != Path(artifacts_dir).resolve():
        raise CorpusError(
            f"the runner is rooted at {runner_cwd}, but the artifacts are in "
            f"{artifacts_dir}. A task run needs a runner whose cwd is the "
            "submission directory, because the CAD CLI resolves targets against it."
        )

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    results: list[SpecResult] = []
    for spec in corpus.specs:
        artifact = resolve_artifact(artifacts_dir, spec.id)
        if artifact is None:
            expected = str(Path(artifacts_dir) / f"{spec.id}{ARTIFACT_SUFFIXES[0]}")
            result = _missing_artifact_result(spec, expected)
        else:
            result = evaluate(spec, artifact, runner)
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
