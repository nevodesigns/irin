"""Driving an agent over a task corpus to produce a submission.

The protocol used to say "hand the prompts to your agent", which for 28 tasks
means 28 manual invocations and 28 chances to paste the wrong thing. This does
it, for any agent that can be run as a command.

**The agent is a command, not an integration.** It receives one prompt on stdin
and returns source on stdout. That is the whole contract, and it is deliberately
the smallest one that works: a CLI, a curl to an API, a shell wrapper around
something else, all satisfy it. Building an adapter per agent would make the
benchmark easier to run against the agents IRIN happened to support and harder
to run against everything else, which is the wrong direction for a number meant
to be comparable.

Nothing here judges the output. An agent that returns prose, an empty file, or
nothing at all produces exactly that, and the run scores it. Cleaning up a bad
submission before measuring it would be measuring the cleanup.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from irinbench.corpus import KIND_TASK, Corpus, CorpusError

#: Agents very often wrap code in markdown fences even when told not to. That is
#: a formatting habit rather than a modelling failure, so it is stripped instead
#: of being scored as broken Python.
_FENCE = re.compile(r"^\s*```(?:python|py)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


@dataclass(frozen=True)
class Submission:
    """What one agent invocation produced for one task."""

    task_id: str
    path: Path | None
    seconds: float
    exit_code: int
    bytes_written: int
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None and self.bytes_written > 0


def strip_fences(text: str) -> str:
    """Remove a single wrapping markdown fence, if the whole reply is one."""
    match = _FENCE.match(text)
    return match.group(1) if match else text


def submit_corpus(
    corpus: Corpus,
    command: str,
    out_dir: str | Path,
    *,
    timeout_s: float = 300.0,
    only: Sequence[str] | None = None,
    on_result: Callable[[Submission], None] | None = None,
) -> tuple[Submission, ...]:
    """Run ``command`` once per task, writing one artifact per task id.

    ``command`` is run through the shell so an operator can pipe and wrap
    freely. It receives the prompt on stdin and its stdout becomes the artifact.
    """
    if corpus.kind != KIND_TASK:
        raise CorpusError(
            f"submissions are produced for a task corpus, not {corpus.kind!r}. "
            "A regression corpus describes models that already exist."
        )

    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    wanted = set(only) if only else None
    results: list[Submission] = []

    for spec in sorted(corpus.specs, key=lambda s: s.id):
        if wanted is not None and spec.id not in wanted:
            continue

        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                input=spec.prompt,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(directory),
            )
            stdout, code, error = completed.stdout, completed.returncode, ""
        except subprocess.TimeoutExpired:
            stdout, code, error = "", 124, f"agent exceeded {timeout_s:g}s"
        except OSError as exc:
            stdout, code, error = "", 1, str(exc)

        elapsed = time.monotonic() - started
        source = strip_fences(stdout).strip()

        path: Path | None = None
        written = 0
        if source:
            path = directory / f"{spec.id}.step.py"
            path.write_text(source + "\n", encoding="utf-8")
            written = len(source)
        elif not error:
            # Ran, returned nothing. Recorded as such rather than as a crash:
            # an agent that answers with silence has still answered.
            error = "agent produced no output"

        result = Submission(
            task_id=spec.id,
            path=path,
            seconds=elapsed,
            exit_code=code,
            bytes_written=written,
            error=error,
        )
        results.append(result)
        if on_result:
            on_result(result)

    return tuple(results)


def format_submissions(results: Sequence[Submission], out_dir: str | Path) -> str:
    produced = [r for r in results if r.ok]
    empty = [r for r in results if not r.ok]
    total_seconds = sum(r.seconds for r in results)

    lines = [
        f"submission: {Path(out_dir)}",
        f"  {len(produced)} of {len(results)} task(s) produced an artifact"
        f"   {total_seconds:.0f}s total",
    ]
    if empty:
        lines.append("")
        lines.append("  nothing written for:")
        for r in empty:
            lines.append(f"    {r.task_id}: {r.error or 'empty output'}")
        lines.append("")
        lines.append("  These are left missing on purpose. The run scores them as")
        lines.append("  artifact_missing, which is a failure and not an error.")
    return "\n".join(lines)
