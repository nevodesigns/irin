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
from irinbench.extract import extract_source
from irinbench.derive import DEFAULT_TOLERANCE_MM, derive_corpus
from irinbench.compare import format_comparison, load_results
from irinbench.report import format_report, format_taxonomy
from irinbench.verify import format_verification, verify_corpus
from irinbench.repair import (
    RepairSession,
    format_session,
    new_session,
    write_briefs,
)
from irinbench.run import reject_unknown_ids, run_corpus, run_task_corpus
from irinbench.probe import format_probe, probe_corpus
from irinbench.submit import format_submissions, submit_corpus

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

    if corpus.kind == KIND_TASK and not args.agent.strip():
        # A task result is a claim about something. A file that cannot name what
        # produced it is not comparable to any other result, and the omission is
        # invisible once the terminal scrollback is gone.
        _log(
            "[irinbench] --agent is required for a task corpus. Name what produced "
            "these artifacts, including model version and any tooling it was given, "
            'for example --agent "gemini-2.5-pro + IRIN cad skill".'
        )
        return 2

    _log(f"[irinbench] running {len(corpus.specs)} spec(s) from {corpus.name}")

    def progress(result) -> None:
        _log(f"[irinbench]   {result.summary_line()}")

    # Check the id filter before a worker is started. It is a pure argument
    # check, and a typo in it should cost one line of output rather than a
    # kernel import, a traceback, and no result.
    try:
        reject_unknown_ids(corpus, set(args.only) if args.only else None)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    artifacts_dir = (Path(args.repo_root) / args.artifacts).resolve() if args.artifacts else None
    with _runner(args, cwd=artifacts_dir if corpus.kind == KIND_TASK else None) as runner:
        if corpus.kind == KIND_TASK:
            run = run_task_corpus(
                corpus,
                artifacts_dir,
                runner,
                repo_root=args.repo_root,
                agent=args.agent,
                only=args.only or None,
                on_result=progress,
            )
        else:
            run = run_corpus(
                corpus,
                runner,
                repo_root=args.repo_root,
                agent=args.agent,
                only=args.only or None,
                on_result=progress,
            )

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


def _score_round(args: argparse.Namespace, corpus, artifacts_dir, agent=""):
    def progress(result) -> None:
        _log(f"[irinbench]   {result.summary_line()}")

    with _runner(args, cwd=artifacts_dir) as runner:
        return run_task_corpus(
            corpus,
            artifacts_dir,
            runner,
            repo_root=args.repo_root,
            agent=agent,
            on_result=progress,
        )


def cmd_repair(args: argparse.Namespace) -> int:
    """Score a round of a repair session and write the briefs for the next one."""
    sessions_root = Path(args.repo_root) / args.sessions
    session_root = sessions_root / args.session

    if session_root.exists():
        try:
            session = RepairSession.load(session_root)
        except CorpusError as exc:
            _log(f"[irinbench] {exc}")
            return 2
        corpus_root = Path(session.corpus_root)
        artifacts_dir = Path(session.artifacts_dir)
        _log(f"[irinbench] continuing session {session.session_id!r} at round {session.round_count}")
    else:
        if not args.artifacts:
            _log(
                "[irinbench] a new session needs --artifacts: the directory holding "
                "what the agent produced."
            )
            return 2
        corpus_root = Path(args.repo_root) / args.corpus
        artifacts_dir = (Path(args.repo_root) / args.artifacts).resolve()
        try:
            corpus = Corpus.load(corpus_root)
        except CorpusError as exc:
            _log(f"[irinbench] {exc}")
            return 2
        session = new_session(args.session, corpus, artifacts_dir, session_root, args.agent)
        _log(f"[irinbench] starting session {session.session_id!r}")

    try:
        corpus = Corpus.load(corpus_root)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    if corpus.kind != KIND_TASK:
        _log(f"[irinbench] repair sessions run against a task corpus, not {corpus.kind}")
        return 2

    index = session.round_count
    session.rounds.append(_score_round(args, corpus, artifacts_dir, session.agent))
    session.save()
    briefs = write_briefs(corpus, session, index)

    _log(f"[irinbench] wrote round {index} to {session.round_path(index)}")
    if briefs:
        _log(f"[irinbench] wrote {len(briefs)} repair brief(s) to {session.brief_dir(index)}")
        _log("[irinbench] revise the artifacts, then run this command again to score the next round.")
    else:
        _log("[irinbench] every task passes; nothing left to repair.")

    print(format_session(session))
    return 0 if not session.unrecovered() else 1


def cmd_prompts(args: argparse.Namespace) -> int:
    """Emit the task prompts, and nothing else.

    What an operator hands to the agent being measured. Deliberately carries no
    assertions and no references: those are the answer key, and an agent that
    saw them would be transcribing rather than designing.

    The corpus fingerprint goes at the top so a submission can be tied to the
    exact requirements it was produced against. A result quoted without one
    cannot be compared to anything.
    """
    try:
        corpus = Corpus.load(Path(args.repo_root) / args.corpus)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    if corpus.kind != KIND_TASK:
        _log(
            f"[irinbench] prompts are for a task corpus. {corpus.name!r} is "
            f"{corpus.kind!r}, whose specs describe models that already exist."
        )
        return 2

    specs = sorted(corpus.specs, key=lambda spec: spec.id)

    if args.json:
        print(json.dumps({
            "corpus": corpus.name,
            "fingerprint": corpus.fingerprint(),
            "count": len(specs),
            "tasks": [
                {"id": s.id, "prompt": s.prompt, "artifact": f"{s.id}.step.py"}
                for s in specs
            ],
        }, indent=2))
        return 0

    width = 72
    out = [
        f"IRIN task corpus: {corpus.name}",
        f"corpus {corpus.short_fingerprint}   {len(specs)} tasks   units mm",
        "",
        "Produce one CAD artifact per task and put them all in one directory.",
        "Name each file after its task id: <task-id>.step.py for build123d",
        "source, or <task-id>.step / <task-id>.stp for an exported solid.",
        "",
        "A task with no artifact is scored as a failure, not as inconclusive.",
        "",
    ]
    for spec in specs:
        out.append("-" * width)
        out.append(f"{spec.id}    ->  {spec.id}.step.py")
        out.append("")
        out.append(spec.prompt)
        out.append("")
    out.append("-" * width)
    print("\n".join(out))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Decode one chat reply on stdin into source on stdout.

    Exists as a command so an adapter can pipe through it rather than
    reimplement it. Every adopter has to decode a reply into a file, and this
    repository got that wrong three times against real models, each time
    publishing a number that was too low without looking wrong.
    """
    source = extract_source(sys.stdin.read())
    sys.stdout.write(source)
    if source and not source.endswith("\n"):
        sys.stdout.write("\n")
    # Silence is a real answer, and the caller has to be able to tell. A model
    # that spent its budget thinking and wrote nothing has not answered, which
    # is a different fact from the request never having been made.
    return 0 if source else 1


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.result)
    if not path.exists():
        _log(f"[irinbench] no such result file: {path}")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    totals = data.get("totals", {})
    rates = data.get("rates", {})
    corpus_block = data.get("corpus", {})

    print(f"IRIN benchmark: {corpus_block.get('name', '?')}")
    print(f"  {data.get('started_at', '?')}  {data.get('duration_s', '?')}s")

    # Provenance, stated every time. A stored number quoted without knowing which
    # corpus produced it is not a result, and the difference is invisible unless
    # something says so out loud.
    recorded = corpus_block.get("fingerprint") or ""
    if not recorded:
        print("  corpus      UNKNOWN: this result predates corpus fingerprints and")
        print("              cannot be tied to a set of requirements. Do not quote it.")
    else:
        print(f"  corpus      {recorded[:12]}")
        # Compare against the corpus this result was scored on, not against a
        # fixed default. Reporting a `tasks` result while the default pointed at
        # `regression` printed "does NOT match this checkout" for a result that
        # matched perfectly well: the warning that exists to catch a stale number
        # was firing on every sound one, which is the fastest way to teach an
        # author to ignore it. An explicit --corpus still wins, because comparing
        # a result against a named corpus on purpose is a real thing to want.
        corpus_dir = args.corpus
        if corpus_dir is None:
            named = corpus_block.get("name")
            corpus_dir = f"benchmarks/{named}" if named else "benchmarks/regression"
        try:
            on_disk = Corpus.load(Path(args.repo_root) / corpus_dir)
        except CorpusError:
            on_disk = None
        if on_disk is not None:
            if on_disk.fingerprint() == recorded:
                print("              matches the corpus in this checkout")
            else:
                print(f"              does NOT match this checkout ({on_disk.short_fingerprint});")
                print("              the two numbers describe different requirements")
    # A partial result says so here as loudly as it does in `run` and `compare`.
    # Without this line a report of 8 of 21 reads as a whole run that went badly,
    # when in fact seven tasks were never attempted and the agent has not been
    # measured on them at all.
    if data.get("partial"):
        held = corpus_block.get("tasks")
        attempted = totals.get("specs")
        print(f"  PARTIAL     {attempted} of {held} tasks attempted;"
              " not comparable to a full run")
    print(f"  specs       {totals.get('specs_passing')} / {totals.get('specs')}"
          f"   {rates.get('spec_pass_rate', 0) * 100:.1f}%")
    print(f"  assertions  {totals.get('assertions_passed')} / {totals.get('assertions')}"
          f"   {rates.get('assertion_pass_rate', 0) * 100:.1f}%")
    if totals.get("assertions_undetermined"):
        print(f"  undetermined {totals['assertions_undetermined']}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Give every task a plain box and report which ones fail to reject it."""
    try:
        corpus = Corpus.load(Path(args.repo_root) / args.corpus)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    _log(f"[irinbench] probing {len(corpus.specs)} task(s) with a plain box")

    def progress(result) -> None:
        _log(f"[irinbench]   {result.summary_line()}")

    def runner_for(directory):
        return WorkerRunner(
            cwd=directory,
            inspect_launcher=args.inspect_launcher or default_inspect_launcher(args.repo_root),
            python_executable=args.python,
            timeout_s=args.timeout,
        )

    try:
        with _runner(args) as reference_runner:
            report = probe_corpus(
                corpus,
                runner_for,
                reference_runner,
                only=args.only or None,
                on_result=progress,
            )
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    print(format_probe(report))
    return 0 if report.ok else 1


def cmd_submit(args: argparse.Namespace) -> int:
    """Run an agent over the corpus and write one artifact per task."""
    try:
        corpus = Corpus.load(Path(args.repo_root) / args.corpus)
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    out_dir = Path(args.repo_root) / args.out
    _log(f"[irinbench] running the agent over {len(corpus.specs)} task(s)")
    _log(f"[irinbench] command: {args.command}")

    def progress(result) -> None:
        if result.ok:
            _log(f"[irinbench]   ok      {result.task_id}  ({result.seconds:.1f}s, {result.bytes_written} bytes)")
        else:
            _log(f"[irinbench]   nothing {result.task_id}  ({result.seconds:.1f}s)  {result.error}")

    try:
        results = submit_corpus(
            corpus,
            args.command,
            out_dir,
            timeout_s=args.agent_timeout,
            only=args.only or None,
            on_result=progress,
        )
    except CorpusError as exc:
        _log(f"[irinbench] {exc}")
        return 2

    print(format_submissions(results, out_dir))
    _log("")
    _log("[irinbench] nothing here has been checked. Score it with:")
    _log(f"[irinbench]   irinbench run --corpus {args.corpus} --artifacts {args.out} --agent \"<name>\"")
    return 0 if any(r.ok for r in results) else 1


def cmd_compare(args: argparse.Namespace) -> int:
    """Put stored results side by side, within a corpus fingerprint."""
    root = Path(args.repo_root) / args.results
    if not root.is_dir():
        _log(f"[irinbench] no results directory at {root}")
        return 2

    paths = sorted(root.glob("*.json"))
    if not paths:
        _log(f"[irinbench] no result files under {root}")
        return 1

    results = load_results(paths)
    print(format_comparison(results))
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
        "--agent",
        default="",
        help=(
            "What produced the artifacts, including model version and any tooling "
            "it was given. Required for a task corpus: a result that cannot name "
            "its agent is not comparable to any other result."
        ),
    )
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
    run.add_argument(
        "--only",
        nargs="*",
        default=None,
        help=(
            "Score only these task ids. The result is marked partial and is not "
            "comparable to a full run. Use when a submission covers part of the "
            "corpus, for instance because a rate limit stopped it."
        ),
    )
    add_common(run, corpus_default="benchmarks/regression")
    run.set_defaults(handler=cmd_run)

    verify = subparsers.add_parser(
        "verify",
        help="Check every task against the reference that proves it satisfiable.",
    )
    add_common(verify, corpus_default="benchmarks/tasks")
    verify.set_defaults(handler=cmd_verify)

    repair = subparsers.add_parser(
        "repair",
        help="Score a round of a repair session and write briefs for the next.",
        description=(
            "Turn based. IRIN scores what the agent produced, writes one brief per "
            "failing task, and stops. Revise the artifacts, then run the same command "
            "again to score the next round. Briefs never contain anything from the "
            "reference implementation."
        ),
    )
    repair.add_argument("--session", required=True, help="Session id; names its directory.")
    repair.add_argument(
        "--sessions", default="benchmarks/sessions", help="Where sessions are kept."
    )
    repair.add_argument(
        "--artifacts",
        default=None,
        help="Directory of the agent's work. Required to start a session.",
    )
    repair.add_argument(
        "--agent",
        default="",
        help=(
            "What produced the artifacts. Recorded once when the session starts "
            "and carried on every round."
        ),
    )
    add_common(repair, corpus_default="benchmarks/tasks")
    repair.set_defaults(handler=cmd_repair)

    prompts = subparsers.add_parser(
        "prompts",
        help="Emit the task prompts for an agent, without the answers.",
        description=(
            "What you hand to the agent being measured. Carries no assertions and "
            "no references, because those are the answer key. The corpus "
            "fingerprint is included so a submission can be tied to the exact "
            "requirements it was produced against."
        ),
    )
    # Only the two it actually uses. prompts reads specs and never touches the
    # CAD kernel, so a --timeout or --inspect-launcher here would be noise.
    prompts.add_argument("--repo-root", default=".", help="Workspace that owns the corpus.")
    prompts.add_argument("--corpus", default="benchmarks/tasks", help="Corpus directory.")
    prompts.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    prompts.set_defaults(handler=cmd_prompts)

    probe = subparsers.add_parser(
        "probe",
        help="Check that each task rejects a plain box of the right size.",
        description=(
            "verify proves a task is satisfiable; this asks the other half. Every "
            "task is given the most charitable wrong answer there is, a sound solid "
            "with the reference's own bounding size and no features, and must reject "
            "it. A task that passes is checking extents rather than the requirement "
            "its prompt states."
        ),
    )
    probe.add_argument("--only", nargs="*", default=None, help="Probe only these task ids.")
    add_common(probe, corpus_default="benchmarks/tasks")
    probe.set_defaults(handler=cmd_probe)

    submit = subparsers.add_parser(
        "submit",
        help="Run an agent over the task corpus and collect its artifacts.",
        description=(
            "The agent is a command, not an integration: it receives one prompt on "
            "stdin and returns source on stdout. A CLI, a curl to an API, or a shell "
            "wrapper all satisfy that. Nothing here judges the output; an agent that "
            "returns prose or nothing produces exactly that, and the run scores it."
        ),
    )
    submit.add_argument("--repo-root", default=".", help="Workspace holding the corpus.")
    submit.add_argument("--corpus", default="benchmarks/tasks", help="Task corpus directory.")
    submit.add_argument("--out", required=True, help="Directory to write artifacts into.")
    submit.add_argument(
        "--command",
        required=True,
        help="Shell command for the agent. Prompt arrives on stdin, source expected on stdout.",
    )
    submit.add_argument(
        "--agent-timeout",
        type=float,
        default=300.0,
        help="Seconds allowed per task before the agent is given up on.",
    )
    submit.add_argument(
        "--only", nargs="*", default=None, help="Run only these task ids."
    )
    submit.set_defaults(handler=cmd_submit)

    compare = subparsers.add_parser(
        "compare",
        help="Put stored results side by side, grouped by corpus fingerprint.",
        description=(
            "One result is a measurement; several are a benchmark, but only if they "
            "were scored against the same requirements. Results are grouped by corpus "
            "fingerprint and compared only within a group, because a table lining up "
            "runs against different corpora would manufacture a comparison that does "
            "not exist."
        ),
    )
    compare.add_argument("--repo-root", default=".", help="Workspace holding the results.")
    compare.add_argument(
        "--results", default="benchmarks/results", help="Directory of result JSON files."
    )
    compare.set_defaults(handler=cmd_compare)

    report = subparsers.add_parser("report", help="Summarize a stored result file.")
    report.add_argument("result", help="Path to a result JSON file.")
    # report needs a corpus only to answer "does this number describe the
    # requirements in this checkout?", so it never runs an inspection.
    report.add_argument("--repo-root", default=".", help="Workspace that owns the corpus.")
    report.add_argument(
        "--corpus",
        default=None,
        help=(
            "Corpus to compare the result's fingerprint against. "
            "Defaults to the one the result names."
        ),
    )
    report.set_defaults(handler=cmd_report)

    extract = subparsers.add_parser(
        "extract",
        help="Decode a chat reply on stdin into CAD source on stdout.",
        description=(
            "Reads one model reply on stdin and writes the source it contains to "
            "stdout. Handles markdown fences, including unbalanced ones left by a "
            "truncated reply, and reasoning emitted before the answer. Exits 1 "
            "when the reply contains no source, which is a real result and not an "
            "error: pipe an adapter through this rather than writing it again."
        ),
    )
    extract.set_defaults(handler=cmd_extract)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "timeout", None) == 0:
        args.timeout = None
    return int(args.handler(args))
