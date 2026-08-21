"""``python -m irinbench``: derive a corpus, run it, report on it.

Streams follow the repository's CLI contract: stdout carries the result, stderr
carries progress and failures. So ``2>/dev/null`` leaves something parseable and
``>/dev/null`` leaves a readable log.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from irineval import WorkerRunner, default_inspect_launcher

from irinbench.corpus import KIND_TASK, Corpus, CorpusError, discover_generators
from irinbench.derive import DEFAULT_TOLERANCE_MM, derive_corpus
from irinbench.report import format_report, format_taxonomy
from irinbench.verify import format_verification, verify_corpus
from irinbench.run import run_corpus, run_task_corpus

DEFAULT_ENTRY_ROOTS = ("models/step/parts", "models/step/assemblies")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _runner(args: argparse.Namespace, *, cwd: str | Path | None = None) -> WorkerRunner:
    """A worker rooted at the workspace that owns the artifacts being inspected.

    For a task run that is the submission directory, not the repository: the CAD
    CLI resolves targets against its own working directory and refuses absolute
    paths outside it, so a submission living anywhere else would be unreadable.
    The launcher is resolved from the repository either way, since that is where
    the skill lives.
    """
    return WorkerRunner(
        cwd=cwd or args.repo_root,
        inspect_launcher=args.inspect_launcher or default_inspect_launcher(args.repo_root),
        python_executable=args.python,
        timeout_s=args.timeout,
    )


def cmd_derive(args: argparse.Namespace) -> int:
    roots = args.entries or list(DEFAULT_ENTRY_ROOTS)
    try:
        generators = discover_generators(Path(args.repo_root) / r for r in roots)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    repo_root = Path(args.repo_root).resolve()
    relative = [str(Path(p).resolve().relative_to(repo_root)) for p in generators]
    _log(f"[irinbench] deriving from {len(relative)} generator(s) in {', '.join(roots)}")

    def progress(entry: str, spec, seconds: float, error: str | None) -> None:
        if error:
            _log(f"[irinbench]   FAILED  {entry}  ({seconds:.1f}s)  {error}")
        else:
            _log(f"[irinbench]   ok      {entry}  ({seconds:.1f}s)")

    with _runner(args) as runner:
        corpus, failures = derive_corpus(
            args.name,
            relative,
            runner,
            Path(args.repo_root) / args.corpus,
            tolerance_mm=args.tolerance,
            include_interference=args.interference,
            on_progress=progress,
        )

    if not corpus.specs:
        _log("[irinbench] no specs derived; refusing to write an empty corpus")
        return 1

    corpus.provenance["derived_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = corpus.save()
    _log(f"[irinbench] wrote {len(corpus.specs)} spec(s) under {corpus.spec_dir}")
    if failures:
        _log(f"[irinbench] {len(failures)} entry(ies) could not be measured:")
        for entry, reason in failures:
            _log(f"[irinbench]   {entry}: {reason}")

    print(manifest)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        corpus = Corpus.load(Path(args.repo_root) / args.corpus)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    _log(f"[irinbench] verifying {len(corpus.specs)} task(s) against their references")

    def progress(result) -> None:
        _log(f"[irinbench]   {result.summary_line()}")

    try:
        with _runner(args) as runner:
            result = verify_corpus(corpus, runner, on_result=progress)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    print(format_verification(result))
    return 0 if result.ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    try:
        corpus = Corpus.load(Path(args.repo_root) / args.corpus)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    if corpus.kind == KIND_TASK and not args.artifacts:
        # No default, deliberately. The only paths a task corpus knows are its
        # references, and scoring those would grade the answer key: every task
        # would pass and the run would report a perfect result measuring nothing.
        _log(
            f"[irinbench] {corpus.name!r} is a task corpus, so --artifacts is required.\n"
            "[irinbench] Point it at the directory holding what an agent produced, "
            "one file per task id.\n"
            "[irinbench] Use `irinbench verify` to check the tasks themselves against "
            "their references."
        )
        return 2

    _log(f"[irinbench] running {len(corpus.specs)} spec(s) from {corpus.name}")

    def progress(result) -> None:
        _log(f"[irinbench]   {result.summary_line()}")

    artifacts_dir = (Path(args.repo_root) / args.artifacts).resolve() if args.artifacts else None
    with _runner(args, cwd=artifacts_dir if corpus.kind == KIND_TASK else None) as runner:
        if corpus.kind == KIND_TASK:
            run = run_task_corpus(
                corpus,
                artifacts_dir,
                runner,
                repo_root=args.repo_root,
                on_result=progress,
            )
        else:
            run = run_corpus(corpus, runner, repo_root=args.repo_root, on_result=progress)

    out = Path(args.repo_root) / (
        args.out or f"benchmarks/results/{corpus.name}-{run.started_at.replace(':', '')}.json"
    )
    run.save(out)
    _log(f"[irinbench] wrote {out}")

    if args.json:
        print(json.dumps(run.to_dict()["totals"], indent=2))
    else:
        print(format_report(run))
        print()
        print("failure taxonomy:")
        print(format_taxonomy(run))

    # Exit non-zero when the corpus did not fully pass, so CI can gate on it.
    return 0 if run.passing == run.total else 1


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.result)
    if not path.exists():
        _log(f"[irinbench] no such result file: {path}")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    rates = data.get("rates", {})
    print(f"IRIN benchmark: {data.get('corpus', {}).get('name', '?')}")
    print(f"  {data.get('started_at', '?')}  {data.get('duration_s', '?')}s")
    print(f"  specs       {totals.get('specs_passing')} / {totals.get('specs')}"
          f"   {rates.get('spec_pass_rate', 0) * 100:.1f}%")
    print(f"  assertions  {totals.get('assertions_passed')} / {totals.get('assertions')}"
          f"   {rates.get('assertion_pass_rate', 0) * 100:.1f}%")
    if totals.get("assertions_undetermined"):
        print(f"  undetermined {totals['assertions_undetermined']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="irinbench",
        description="Derive, run and report IRIN benchmark corpora.",
    )
    def add_common(sub: argparse.ArgumentParser, *, corpus_default: str) -> None:
        """Options every corpus command takes.

        Declared on each subcommand rather than once at the top level. argparse
        only accepts a top-level option BEFORE the subcommand, and nobody types
        `irinbench --corpus x run`; they type `irinbench run --corpus x`.
        """
        sub.add_argument("--repo-root", default=".", help="Workspace that owns the models.")
        sub.add_argument("--corpus", default=corpus_default, help="Corpus directory.")
        sub.add_argument(
            "--inspect-launcher", default=None, help="Path to the CAD inspect launcher."
        )
        sub.add_argument("--python", default=None, help="Interpreter used to run inspect.")
        sub.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help=(
                "Seconds allowed per inspection before it is abandoned and reported as "
                "undetermined. Without a budget one pathological model stops the run "
                "indefinitely, which in CI is indistinguishable from a hang. 0 disables it."
            ),
        )

    subparsers = parser.add_subparsers(dest="command", required=True)

    derive = subparsers.add_parser("derive", help="Measure models and write a regression corpus.")
    derive.add_argument("--name", default="regression", help="Corpus name.")
    derive.add_argument("--entries", nargs="*", help="Directories of *.step.py entries.")
    derive.add_argument(
        "--tolerance", type=float, default=DEFAULT_TOLERANCE_MM, help="Dimensional band in mm."
    )
    derive.add_argument(
        "--interference",
        action="store_true",
        help=(
            "Also measure and record the clash count. Off by default: it is the most "
            "expensive inspection by a wide margin."
        ),
    )
    add_common(derive, corpus_default="benchmarks/regression")
    derive.set_defaults(handler=cmd_derive)

    run = subparsers.add_parser("run", help="Evaluate a corpus and write a result file.")
    run.add_argument("--out", default=None, help="Result file path.")
    run.add_argument(
        "--artifacts",
        default=None,
        help=(
            "Directory holding what an agent produced, one file per task id "
            "(<id>.step.py, .step or .stp). Required for a task corpus, which has "
            "no artifacts of its own to score."
        ),
    )
    run.add_argument("--json", action="store_true", help="Print totals as JSON instead of a report.")
    add_common(run, corpus_default="benchmarks/regression")
    run.set_defaults(handler=cmd_run)

    verify = subparsers.add_parser(
        "verify",
        help="Check every task against the reference that proves it satisfiable.",
    )
    add_common(verify, corpus_default="benchmarks/tasks")
    verify.set_defaults(handler=cmd_verify)

    report = subparsers.add_parser("report", help="Summarize a stored result file.")
    report.add_argument("result", help="Path to a result JSON file.")
    report.set_defaults(handler=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "timeout", None) == 0:
        args.timeout = None
    return int(args.handler(args))
