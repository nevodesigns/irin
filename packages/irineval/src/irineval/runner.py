"""Talking to the CAD inspection CLI.

IRIN evaluates geometry by driving the existing ``inspect`` CLI rather than
importing the CAD runtime into this process. Two reasons, both practical:

* **Isolation.** The kernel underneath is OpenCascade. A boolean that segfaults
  or a self-intersection test that runs away takes its own process with it and
  the benchmark keeps going, instead of losing the whole run.
* **Weight.** Nothing here depends on build123d. A report generator, a CI check
  and a diffing tool can all import this module without installing a CAD kernel.

``inspect`` speaks JSONL over a persistent worker:

    stdin   {"id": 3, "argv": ["validate", "path/to/model.step.py"]}
    stdout  {"id": 3, "ok": true, "exitCode": 0, "result": {...}}

That worker is the whole reason a spec-sized evaluation is affordable. Starting
a fresh process per assertion pays the OpenCascade import every time, which
dominates everything else a small part costs to check.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence


class EvalError(RuntimeError):
    """The evaluator could not run, as distinct from an artifact being wrong."""


class InspectTimeout(EvalError):
    """One inspection exceeded its budget and the worker was restarted.

    Not a hypothetical. A single assembly in the reference corpus held the CPU
    for over twenty minutes inside one ``validate`` call. Without a budget a
    benchmark simply stops there: in CI that is indistinguishable from a hang,
    and a run that never finishes reports nothing at all.
    """


@dataclass(frozen=True)
class InspectResponse:
    """One answer from the inspection CLI."""

    ok: bool
    exit_code: int
    result: dict

    def error_messages(self) -> tuple[str, ...]:
        errors = self.result.get("errors")
        if not isinstance(errors, list):
            return ()
        out = []
        for item in errors:
            if isinstance(item, dict) and item.get("message"):
                out.append(str(item["message"]))
            elif isinstance(item, str):
                out.append(item)
        return tuple(out)

    def first_error(self) -> str:
        messages = self.error_messages()
        if messages:
            return messages[0]
        return f"inspect exited {self.exit_code}"


class InspectRunner(Protocol):
    """Anything that can answer an inspect argv.

    A protocol rather than a base class so tests can supply recorded responses
    without a CAD runtime, and so a future remote or cached runner drops in
    without touching the evaluator.
    """

    def run(self, argv: Sequence[str]) -> InspectResponse: ...


def default_inspect_launcher(repo_root: str | Path | None = None) -> Path:
    """Locate the CAD skill's inspect launcher.

    Looks for an installed skill layout first, then the repository checkout, so
    the evaluator works both from a source tree and from an installed skill.
    """
    root = Path(repo_root) if repo_root else Path.cwd()
    candidates = [
        root / "skills" / "cad" / "scripts" / "inspect",
        root / "scripts" / "inspect",
    ]
    for candidate in candidates:
        if candidate.exists():
            # Absolute, always. A task run roots its worker at the submission
            # directory, and a launcher path relative to the repository would
            # simply not exist from there: python exits 2 and every inspection
            # in the run reports as undetermined.
            return candidate.resolve()
    raise EvalError(
        "cannot find the CAD inspect launcher. Looked in:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\nPass inspect_launcher explicitly when the skill lives elsewhere."
    )


class WorkerRunner:
    """One long-lived ``inspect worker`` process, driven over JSONL.

    Use as a context manager. The process is started lazily on the first
    request, so constructing a runner for a spec that turns out to need no
    inspections costs nothing.

    ``cwd`` matters and is not optional in practice: inspect resolves target
    paths against the working directory of the command, so a runner started in
    the wrong place reports that a model does not exist.

    ``timeout_s`` bounds each request. It defaults to no budget, because an
    interactive caller checking one model should wait for the answer rather than
    lose it. A benchmark passes one.
    """

    def __init__(
        self,
        *,
        cwd: str | Path,
        inspect_launcher: str | Path | None = None,
        python_executable: str | None = None,
        env: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.cwd = Path(cwd)
        if not self.cwd.is_dir():
            raise EvalError(f"cwd {self.cwd} is not a directory")
        self.launcher = Path(inspect_launcher) if inspect_launcher else default_inspect_launcher(self.cwd)
        self.python = python_executable or sys.executable
        self.timeout_s = timeout_s
        self._env = env
        self._process: subprocess.Popen | None = None
        self._next_id = 0
        self.timeouts = 0

    # -- lifecycle ------------------------------------------------------------

    def __enter__(self) -> "WorkerRunner":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _start(self) -> subprocess.Popen:
        if self._process is not None and self._process.poll() is None:
            return self._process
        env = dict(os.environ if self._env is None else self._env)
        try:
            self._process = subprocess.Popen(
                [self.python, str(self.launcher), "worker"],
                cwd=str(self.cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=env,
            )
        except OSError as exc:
            raise EvalError(f"could not start the inspect worker: {exc}") from exc
        return self._process

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            # Closing stdin is what asks the worker to finish: it reads until EOF.
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except OSError:
            pass
        finally:
            # stdout is a pipe we own. Leaving it open leaks a file descriptor
            # per runner, which a benchmark creating one per workspace would
            # notice long before a person did.
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def _kill(self) -> None:
        """Tear the worker down hard, for a request that will not come back."""
        process = self._process
        self._process = None
        if process is None:
            return
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    # -- requests -------------------------------------------------------------

    def _read_line(self, process: subprocess.Popen, argv: Sequence[str]) -> str:
        """One response line, or give up after ``timeout_s``.

        Reading on a separate thread is what makes the budget enforceable: the
        blocking read cannot be interrupted, so the only way out is to stop
        waiting for it and kill the process it is blocked on.

        The worker is killed rather than reused, because an abandoned request
        leaves the response stream in an unknown state. Reusing it would let the
        next answer belong to the request that was given up on, and every result
        after that would be attributed to the wrong assertion.
        """
        assert process.stdout is not None

        if self.timeout_s is None:
            line = process.stdout.readline()
            if not line:
                raise EvalError(
                    f"the inspect worker closed its output while answering {list(argv)} "
                    f"(exit code {process.poll()})"
                )
            return line

        box: "queue.Queue[str]" = queue.Queue(maxsize=1)

        def reader() -> None:
            try:
                box.put(process.stdout.readline())  # type: ignore[union-attr]
            except (ValueError, OSError):
                box.put("")

        threading.Thread(target=reader, daemon=True).start()
        try:
            line = box.get(timeout=self.timeout_s)
        except queue.Empty:
            self.timeouts += 1
            self._kill()
            raise InspectTimeout(
                f"inspect exceeded {self.timeout_s:g}s answering {list(argv)}; "
                "the worker was restarted and this check is undetermined"
            ) from None

        if not line:
            raise EvalError(
                f"the inspect worker closed its output while answering {list(argv)} "
                f"(exit code {process.poll()})"
            )
        return line

    def run(self, argv: Sequence[str]) -> InspectResponse:
        process = self._start()
        self._next_id += 1
        request_id = self._next_id
        payload = json.dumps({"id": request_id, "argv": [str(a) for a in argv]})

        assert process.stdin is not None
        try:
            process.stdin.write(payload + "\n")
            process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise EvalError(
                f"the inspect worker exited before answering {list(argv)}: {exc}"
            ) from exc

        line = self._read_line(process, argv)

        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"the inspect worker returned unparseable output: {line!r}") from exc

        # The worker echoes the id. A mismatch means responses and requests have
        # drifted out of step, and every result after it would be attributed to
        # the wrong assertion.
        echoed = response.get("id")
        if echoed is not None and echoed != request_id:
            raise EvalError(
                f"inspect worker replied to request {echoed} while request {request_id} "
                "was outstanding; the response stream is out of step"
            )

        result = response.get("result")
        return InspectResponse(
            ok=bool(response.get("ok")),
            exit_code=int(response.get("exitCode", 1)),
            result=result if isinstance(result, dict) else {},
        )


class RecordedRunner:
    """Replays canned responses. For tests, and for re-scoring a stored run.

    Keyed by the argv tuple so a test states exactly which inspection it is
    answering, and an unexpected call fails loudly rather than returning
    something plausible.
    """

    def __init__(self, responses: dict[tuple[str, ...], InspectResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str]) -> InspectResponse:
        key = tuple(str(a) for a in argv)
        self.calls.append(key)
        if key not in self._responses:
            raise EvalError(
                f"no recorded response for {list(key)}. Recorded: "
                + ", ".join(str(list(k)) for k in self._responses)
            )
        return self._responses[key]

    def call_count(self, prefix: str) -> int:
        return sum(1 for call in self.calls if call and call[0] == prefix)


def responses_from_pairs(pairs: Iterable[tuple[Sequence[str], dict]]) -> dict[tuple[str, ...], InspectResponse]:
    """Build a RecordedRunner table from ``(argv, result)`` pairs."""
    table: dict[tuple[str, ...], InspectResponse] = {}
    for argv, result in pairs:
        ok = bool(result.get("ok", True))
        table[tuple(str(a) for a in argv)] = InspectResponse(
            ok=ok, exit_code=0 if ok else 1, result=result
        )
    return table
