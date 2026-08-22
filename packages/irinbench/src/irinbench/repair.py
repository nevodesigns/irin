"""The repair loop: does feedback actually help?

Generating correct geometry first time is one capability. Reading a failure
report and fixing the thing is a different one, and for engineering work it is
the more important of the two. A model that lands 40% first time and recovers
most of the rest is more useful than one that lands 55% and cannot move.

Nothing measures the second capability today, for any CAD agent, because
measuring it needs three things at once: a requirement precise enough to fail
against, a diagnosis specific enough to act on, and accounting that survives
across rounds. The first two now exist.

**IRIN does not do the repairing.** It cannot invoke arbitrary agents, and
pretending otherwise would tie the benchmark to whichever one it happened to
support. A session is turn-based: IRIN scores, writes a brief per failing task,
and stops. The operator's agent revises the artifacts. IRIN scores again. The
accounting is what IRIN owns.

**A brief never contains the answer.** Every task has a reference
implementation, and putting any of it in front of the agent would turn repair
into copying and the metric into nothing. A brief carries the original
requirement, the assertions that failed with their measured values, and the
assertions that already pass and must keep passing. Nothing else.

That last part matters more than it looks. A repair that fixes the reported
failure and breaks something that was already right is a real and common
outcome, and a loop that only counts recoveries would score it as progress.
Regressions are tracked separately.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from irineval import FailureCode, SpecResult

from irinbench.corpus import KIND_TASK, Corpus, CorpusError
from irinbench.run import RunResult

SESSION_FILE = "session.json"
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass
class RepairSession:
    """One agent, one corpus, one or more rounds of revision."""

    session_id: str
    corpus_name: str
    corpus_root: str
    artifacts_dir: str
    root: Path
    #: What produced the artifacts. Carried on every round, so a session that
    #: outlives its terminal still names what it measured.
    agent: str = ""
    rounds: list[RunResult] = field(default_factory=list)
    started_at: str = ""

    def __post_init__(self) -> None:
        if not _ID_PATTERN.match(self.session_id):
            raise CorpusError(
                f"session id must be a lowercase slug, got {self.session_id!r}. "
                "It names a directory and appears in every report."
            )

    # -- accounting -----------------------------------------------------------

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    def _ok_ids(self, index: int) -> set[str]:
        return {result.spec_id for result in self.rounds[index].results if result.ok}

    def first_pass(self) -> set[str]:
        """Tasks correct before any feedback was given."""
        return self._ok_ids(0) if self.rounds else set()

    def recovered_at(self) -> dict[int, set[str]]:
        """Tasks that first passed at round n, for n >= 1.

        "First passed" rather than "passed", so a task cannot be counted twice
        and the rounds sum to something meaningful.
        """
        out: dict[int, set[str]] = {}
        seen = self.first_pass()
        for index in range(1, self.round_count):
            newly = self._ok_ids(index) - seen
            if newly:
                out[index] = newly
            seen |= newly
        return out

    def regressed(self) -> dict[int, set[str]]:
        """Tasks that were passing and stopped, per round.

        A repair that fixes what was reported and breaks what was not is a real
        outcome, and one a loop counting only recoveries would score as
        progress.
        """
        out: dict[int, set[str]] = {}
        for index in range(1, self.round_count):
            lost = self._ok_ids(index - 1) - self._ok_ids(index)
            if lost:
                out[index] = lost
        return out

    def unrecovered(self) -> set[str]:
        """Still failing after the final round."""
        if not self.rounds:
            return set()
        last = self.rounds[-1]
        return {result.spec_id for result in last.results if not result.ok}

    def metrics(self) -> dict[str, Any]:
        total = self.rounds[0].total if self.rounds else 0
        recovered = self.recovered_at()
        return {
            "tasks": total,
            "rounds": self.round_count,
            "first_pass": len(self.first_pass()),
            "recovered_at": {str(k): len(v) for k, v in sorted(recovered.items())},
            "recovered_total": sum(len(v) for v in recovered.values()),
            "regressed": {str(k): sorted(v) for k, v in sorted(self.regressed().items())},
            "unrecovered": len(self.unrecovered()),
            "rates": {
                "first_pass": round(len(self.first_pass()) / total, 6) if total else 0.0,
                "final": round(
                    (total - len(self.unrecovered())) / total, 6
                )
                if total
                else 0.0,
            },
        }

    # -- persistence ----------------------------------------------------------

    @property
    def session_path(self) -> Path:
        return self.root / SESSION_FILE

    def round_path(self, index: int) -> Path:
        return self.root / f"round-{index}.json"

    def brief_dir(self, index: int) -> Path:
        return self.root / f"round-{index}-briefs"

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        for index, result in enumerate(self.rounds):
            result.save(self.round_path(index))
        payload = {
            "session": self.session_id,
            "corpus": {"name": self.corpus_name, "root": self.corpus_root},
            "artifacts": self.artifacts_dir,
            "agent": self.agent,
            "started_at": self.started_at,
            "rounds": self.round_count,
            "metrics": self.metrics(),
        }
        self.session_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.session_path

    @classmethod
    def load(cls, root: str | Path) -> "RepairSession":
        directory = Path(root)
        path = directory / SESSION_FILE
        if not path.exists():
            raise CorpusError(f"no repair session at {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        session = cls(
            session_id=payload["session"],
            corpus_name=payload["corpus"]["name"],
            corpus_root=payload["corpus"]["root"],
            artifacts_dir=payload["artifacts"],
            root=directory,
            agent=payload.get("agent", ""),
            started_at=payload.get("started_at", ""),
        )
        # Round results are reloaded as recorded rather than recomputed: a
        # session is a history, and rescoring it later against changed code
        # would quietly rewrite what happened.
        for index in range(int(payload.get("rounds", 0))):
            session.rounds.append(_load_round(session.round_path(index)))
        return session


def _load_round(path: Path) -> RunResult:
    data = json.loads(path.read_text(encoding="utf-8"))
    from irineval import AssertionResult

    results = []
    for entry in data.get("results", []):
        assertions = tuple(
            AssertionResult(
                kind=a.get("kind", ""),
                description=a.get("description", ""),
                passed=bool(a.get("passed")),
                code=FailureCode(a["code"]) if a.get("code") else None,
                detail=a.get("detail", ""),
                expected=a.get("expected"),
                actual=a.get("actual"),
                deviation=a.get("deviation"),
                excess=a.get("excess"),
            )
            for a in entry.get("assertions", [])
        )
        results.append(
            SpecResult(
                spec_id=entry.get("spec", ""),
                entry=entry.get("entry", ""),
                results=assertions,
                inspections=tuple(entry.get("inspections", [])),
                duration_s=entry.get("duration_s"),
            )
        )
    return RunResult(
        corpus_name=data.get("corpus", {}).get("name", ""),
        corpus_kind=data.get("corpus", {}).get("kind", ""),
        corpus_fingerprint=data.get("corpus", {}).get("fingerprint", ""),
        results=tuple(results),
        started_at=data.get("started_at", ""),
        duration_s=float(data.get("duration_s", 0.0)),
        environment=data.get("environment", {}),
    )


# ---------------------------------------------------------------------------
# briefs
# ---------------------------------------------------------------------------


def repair_brief(spec, result: SpecResult, *, round_index: int) -> str:
    """What the agent is told about one failing task.

    Contains the requirement, what failed with the measured value, and what
    already passes. Contains nothing from the reference implementation, because
    a brief that leaked it would turn repair into transcription and the
    resulting number into a measure of copying.
    """
    lines = [
        f"# {spec.id}",
        "",
        f"Round {round_index}. This artifact does not yet satisfy its requirement.",
        "",
        "## The requirement",
        "",
        spec.prompt,
        "",
        "## What is wrong",
        "",
    ]

    missing = all(a.code == FailureCode.ARTIFACT_MISSING for a in result.results)
    if missing:
        lines.append(
            f"No artifact was found for this task. Produce one at `{result.entry}`."
        )
    else:
        for assertion in result.failures():
            if assertion.undetermined:
                lines.append(
                    f"- **{assertion.kind}** could not be checked: {assertion.detail}"
                )
                lines.append(
                    "  This is a tooling failure rather than a defect. The artifact may "
                    "or may not be correct here."
                )
                continue
            lines.append(f"- **{assertion.kind}**: {assertion.description}")
            if assertion.detail:
                lines.append(f"  {assertion.detail}")
            if assertion.excess:
                lines.append(f"  Out by {assertion.excess:+g} mm.")

    passing = [a for a in result.results if a.passed]
    if passing:
        lines += [
            "",
            "## What is already right",
            "",
            "These pass now and must still pass after the change:",
            "",
        ]
        lines += [f"- {a.kind}: {a.description}" for a in passing]

    lines += [
        "",
        "## What to do",
        "",
        f"Revise `{result.entry}`, then submit it again. Change the smallest thing "
        "that fixes the failures above without disturbing what already passes.",
        "",
    ]
    return "\n".join(lines)


def write_briefs(corpus: Corpus, session: RepairSession, round_index: int) -> tuple[Path, ...]:
    """One brief per failing task. Returns the paths written."""
    if corpus.kind != KIND_TASK:
        raise CorpusError("repair briefs are written for task corpora only")

    by_id = {spec.id: spec for spec in corpus.specs}
    directory = session.brief_dir(round_index)
    directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for result in session.rounds[round_index].results:
        if result.ok:
            continue
        spec = by_id.get(result.spec_id)
        if spec is None:
            continue
        path = directory / f"{result.spec_id}.md"
        path.write_text(repair_brief(spec, result, round_index=round_index), encoding="utf-8")
        written.append(path)
    return tuple(written)


def new_session(
    session_id: str,
    corpus: Corpus,
    artifacts_dir: str | Path,
    root: str | Path,
    agent: str = "",
) -> RepairSession:
    return RepairSession(
        session_id=session_id,
        corpus_name=corpus.name,
        corpus_root=str(corpus.root),
        artifacts_dir=str(artifacts_dir),
        root=Path(root),
        agent=agent,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def format_session(session: RepairSession) -> str:
    """The table this whole loop exists to produce."""
    metrics = session.metrics()
    total = metrics["tasks"] or 1
    lines = [
        f"IRIN repair session: {session.session_id}",
        f"  agent  {session.agent or 'unnamed'}",
        f"  corpus {session.corpus_name}   {metrics['rounds']} round(s)   "
        f"{metrics['tasks']} task(s)",
        "",
    ]

    def row(label: str, count: int) -> str:
        return f"  {label:<26} {count:>3}   {count / total * 100:5.1f}%"

    lines.append(row("first pass", metrics["first_pass"]))
    for index, count in metrics["recovered_at"].items():
        lines.append(row(f"recovered after {index} repair" + ("" if index == "1" else "s"), count))
    lines.append(row("unrecovered", metrics["unrecovered"]))

    if metrics["regressed"]:
        lines.append("")
        lines.append("  regressions, which a recovery count alone would hide:")
        for index, ids in metrics["regressed"].items():
            lines.append(f"    round {index}: {', '.join(ids)}")

    lines.append("")
    lines.append(
        f"  final {metrics['rates']['final'] * 100:.1f}% "
        f"(from {metrics['rates']['first_pass'] * 100:.1f}% before any feedback)"
    )
    return "\n".join(lines)
