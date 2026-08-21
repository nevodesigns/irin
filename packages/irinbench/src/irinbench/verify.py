"""Proving a task corpus is worth running.

A task spec is written from intent, which means nothing has checked it against
reality. Two failure modes follow, and both are quiet.

A spec can be **unsatisfiable**. "Six 6 mm holes on a 60 mm bolt circle in an
80 mm flange" is checkable arithmetic; "six 30 mm holes on a 60 mm bolt circle"
is not buildable at all, and nothing in the schema would object. An agent scored
against it fails through no fault of its own, and the benchmark reports a model
weakness that is actually an author's mistake.

A spec can be **wrong about its own units or geometry**. A radius written where
a diameter was meant passes every schema check and every tolerance check, and
simply measures the wrong thing forever.

The defence is a reference implementation: a model that genuinely satisfies the
requirement, which the spec was *not* derived from. If the spec passes its
reference, the requirement is buildable and the assertions describe it. If it
fails, the spec is broken and must not ship.

This is the one place a task corpus is allowed to touch a reference. Scoring a
run against one would grade the answer key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from irineval import InspectRunner, SpecResult, evaluate

from irinbench.corpus import KIND_TASK, Corpus, CorpusError


@dataclass
class VerifyResult:
    """Whether each task in a corpus is provably satisfiable."""

    corpus_name: str
    verified: tuple[SpecResult, ...] = ()
    unreferenced: tuple[str, ...] = ()
    errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def satisfiable(self) -> tuple[SpecResult, ...]:
        return tuple(result for result in self.verified if result.ok)

    @property
    def broken(self) -> tuple[SpecResult, ...]:
        """Specs their own reference fails. These must not ship."""
        return tuple(result for result in self.verified if not result.ok)

    @property
    def ok(self) -> bool:
        return not self.broken and not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus_name,
            "checked": len(self.verified),
            "satisfiable": len(self.satisfiable),
            "broken": [result.spec_id for result in self.broken],
            "unreferenced": list(self.unreferenced),
            "errors": [{"spec": spec, "message": message} for spec, message in self.errors],
            "ok": self.ok,
        }


def verify_corpus(
    corpus: Corpus,
    runner: InspectRunner,
    *,
    on_result: Callable[[SpecResult], None] | None = None,
) -> VerifyResult:
    """Check every task against the reference that proves it buildable."""
    if corpus.kind != KIND_TASK:
        raise CorpusError(
            f"only a task corpus is verified against references; {corpus.name!r} is "
            f"a {corpus.kind} corpus, whose specs were measured from their models "
            "and therefore pass by construction."
        )

    results: list[SpecResult] = []
    errors: list[tuple[str, str]] = []

    for spec in corpus.specs:
        reference = corpus.reference_for(spec)
        if reference is None:
            continue
        try:
            result = evaluate(spec, reference, runner)
        except Exception as exc:  # noqa: BLE001 - a broken reference is a finding
            errors.append((spec.id, str(exc)))
            continue
        results.append(result)
        if on_result:
            on_result(result)

    return VerifyResult(
        corpus_name=corpus.name,
        verified=tuple(results),
        unreferenced=corpus.unreferenced(),
        errors=tuple(errors),
    )


def format_verification(result: VerifyResult) -> str:
    lines = [f"IRIN task verification: {result.corpus_name}", ""]
    lines.append(f"  satisfiable  {len(result.satisfiable)} / {len(result.verified)}")
    if result.unreferenced:
        lines.append(
            f"  unreferenced {len(result.unreferenced)} "
            "(authored, but nothing yet proves them buildable)"
        )
        for spec_id in result.unreferenced:
            lines.append(f"      {spec_id}")

    if result.broken:
        lines.append("")
        lines.append("  specs their own reference fails, which must be fixed before shipping:")
        for spec_result in result.broken:
            lines.append("")
            lines.append(f"    {spec_result.spec_id}  ({spec_result.entry})")
            for assertion in spec_result.failures():
                code = assertion.code.value if assertion.code else "failed"
                lines.append(
                    f"      {assertion.kind:<14} [{code}] "
                    f"{assertion.detail or assertion.description}"
                )

    if result.errors:
        lines.append("")
        lines.append("  references that could not be evaluated:")
        for spec_id, message in result.errors:
            lines.append(f"    {spec_id}: {message}")

    if result.ok:
        lines.append("")
        lines.append("  every referenced task is satisfiable")
    return "\n".join(lines)
