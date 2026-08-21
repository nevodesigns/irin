"""IRIN geometry evaluation: check a spec's assertions against real geometry.

Drives the CAD skill's ``inspect`` CLI over its JSONL worker, so the CAD kernel
stays in its own process and nothing here imports build123d.

    from irinspec import Spec, Size, ValidSolid
    from irineval import WorkerRunner, evaluate

    with WorkerRunner(cwd=".") as runner:
        result = evaluate(spec, "models/step/parts/block.step.py", runner)

    print(result.summary_line())
    for failure in result.failures():
        print(" ", failure.detail)
"""

from irineval.evaluator import evaluate, evaluate_all, inspect_argv, measured_clashes, measured_facts, plan
from irineval.results import (
    DEFECT_CODES,
    UNDETERMINED_CODES,
    AssertionResult,
    FailureCode,
    SpecResult,
)
from irineval.runner import (
    EvalError,
    InspectTimeout,
    InspectResponse,
    InspectRunner,
    RecordedRunner,
    WorkerRunner,
    default_inspect_launcher,
    responses_from_pairs,
)

__all__ = [
    "AssertionResult",
    "DEFECT_CODES",
    "EvalError",
    "FailureCode",
    "InspectResponse",
    "InspectTimeout",
    "InspectRunner",
    "RecordedRunner",
    "SpecResult",
    "UNDETERMINED_CODES",
    "WorkerRunner",
    "default_inspect_launcher",
    "evaluate",
    "evaluate_all",
    "inspect_argv",
    "measured_clashes",
    "measured_facts",
    "plan",
    "responses_from_pairs",
]
