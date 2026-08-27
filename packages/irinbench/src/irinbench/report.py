"""Turning a run into something a person reads in ten seconds.

Failures first, and each one carrying the measured number. A report that says
"12 failed" makes you open a JSON file; one that says "z: 20 is outside
[23.8, 24.2] by -3.8 mm" tells you which parameter to change.

Undetermined is always shown on its own line rather than folded into a failure
count, because the two demand different work: a defect is a model to fix, an
undetermined is tooling to fix.
"""

from __future__ import annotations

from irineval import FailureCode

from irinbench.run import RunResult

_BAR_WIDTH = 28


def _bar(fraction: float, width: int = _BAR_WIDTH) -> str:
    filled = round(fraction * width)
    return "#" * filled + "." * (width - filled)


def format_report(run: RunResult, *, max_failures: int = 25) -> str:
    """A plain-text report. No colour, so it reads the same in a log or a file."""
    lines: list[str] = []
    add = lines.append

    add(f"IRIN benchmark: {run.corpus_name} ({run.corpus_kind})")
    if run.corpus_fingerprint:
        add(f"  corpus {run.corpus_fingerprint[:12]}")
    if run.partial:
        add(f"  PARTIAL: {run.total} of {run.corpus_task_count} tasks attempted,"
            " not comparable to a full run")
    add(f"  version {run.environment.get('irin_version', 'unknown')}"
        f"  python {run.environment.get('python', '?')}")
    add(f"  {run.started_at}   {run.duration_s:.1f}s")
    add("")

    add(f"  specs       {run.passing:>4} / {run.total:<4}  {_bar(run.spec_pass_rate)}  "
        f"{run.spec_pass_rate * 100:5.1f}%")
    add(f"  assertions  {run.assertions_passed:>4} / {run.assertions_total:<4}  "
        f"{_bar(run.assertion_pass_rate)}  {run.assertion_pass_rate * 100:5.1f}%")

    if run.with_defects:
        add(f"  specs with defects       {run.with_defects}")
    if run.with_undetermined:
        add(f"  specs with undetermined  {run.with_undetermined} "
            f"({run.assertions_undetermined} assertions could not be established)")

    failures = run.failures()
    if not failures:
        add("")
        add("  no failures")
        return "\n".join(lines)

    add("")
    add(f"  {len(failures)} spec(s) not fully passing:")
    for result in failures[:max_failures]:
        add("")
        add(f"  {result.spec_id}")
        add(f"    {result.entry}")
        for assertion in result.failures():
            code = assertion.code.value if assertion.code else "failed"
            marker = "?" if assertion.undetermined else "x"
            detail = assertion.detail or assertion.description
            add(f"    {marker} {assertion.kind:<16} [{code}] {detail}")
    if len(failures) > max_failures:
        add("")
        add(f"  ... and {len(failures) - max_failures} more, see the result file")

    return "\n".join(lines)


def failure_taxonomy(run: RunResult) -> dict[str, int]:
    """How many assertions failed for each reason.

    The shape of a run matters more than its score. Thirty dimension misses is a
    modelling problem; thirty inspection failures is a broken toolchain, and the
    single number is identical in both cases.
    """
    counts: dict[str, int] = {code.value: 0 for code in FailureCode}
    for result in run.results:
        for assertion in result.failures():
            if assertion.code is not None:
                counts[assertion.code.value] += 1
    return {code: n for code, n in counts.items() if n}


def format_taxonomy(run: RunResult) -> str:
    counts = failure_taxonomy(run)
    if not counts:
        return "  no failures to classify"
    width = max(len(code) for code in counts)
    return "\n".join(
        f"  {code:<{width}}  {n}" for code, n in sorted(counts.items(), key=lambda kv: -kv[1])
    )
