"""IRIN benchmarking: corpora of specs, runs against them, and reports.

Two kinds of corpus, kept apart on purpose:

**regression** is derived by measuring models that already exist. It detects
drift in the geometry pipeline, and the models pass it by construction.

**task** states intent in the prompt and is scored on what an agent builds. Its
assertions come from the requirement, not from an answer, so it has to be
authored rather than derived.

Conflating them would let a green regression run be reported as evidence that an
agent builds correct geometry, which it is not.
"""

from irinbench.compare import StoredResult, format_comparison, group_by_corpus, load_results
from irinbench.corpus import (
    KIND_REGRESSION,
    KIND_TASK,
    KINDS,
    Corpus,
    CorpusError,
    discover_generators,
    spec_id_for,
)
from irinbench.derive import DEFAULT_TOLERANCE_MM, derive_corpus, derive_spec
from irinbench.report import failure_taxonomy, format_report, format_taxonomy
from irinbench.repair import (
    RepairSession,
    format_session,
    new_session,
    repair_brief,
    write_briefs,
)
from irinbench.run import RunResult, run_corpus, run_task_corpus
from irinbench.submit import Submission, format_submissions, strip_fences, submit_corpus
from irinbench.verify import VerifyResult, format_verification, verify_corpus

__all__ = [
    "Corpus",
    "StoredResult",
    "Submission",
    "CorpusError",
    "DEFAULT_TOLERANCE_MM",
    "KINDS",
    "KIND_REGRESSION",
    "KIND_TASK",
    "RepairSession",
    "RunResult",
    "VerifyResult",
    "derive_corpus",
    "derive_spec",
    "discover_generators",
    "failure_taxonomy",
    "format_comparison",
    "format_report",
    "group_by_corpus",
    "load_results",
    "format_taxonomy",
    "format_session",
    "format_verification",
    "new_session",
    "repair_brief",
    "format_submissions",
    "run_corpus",
    "strip_fences",
    "submit_corpus",
    "run_task_corpus",
    "verify_corpus",
    "write_briefs",
    "spec_id_for",
]
