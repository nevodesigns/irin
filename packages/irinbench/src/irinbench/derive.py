"""Building a regression corpus by measuring models that already exist.

What this produces is a **golden master**, and it is worth being precise about
what that is and is not.

It **is** a real check. Every assertion records what the geometry measures
today, so a change to the CAD engine, a dependency bump, or an accidental edit
to a generator shows up as a named dimension moving by a named amount, on any of
fifty models at once. Nothing in the repository does that today.

It is **not** an agent benchmark. The assertions come from the model, so the
model passes them by construction. Asking whether an agent can build the right
thing needs a prompt written from intent, and assertions written from the
requirement rather than read off the answer. Those have to be authored, which is
why a task corpus is a separate kind rather than something this file can fake.

The prompt on a derived spec says so plainly, so a task corpus cannot be
mistaken for one of these later.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Sequence

from irinspec import (
    Bounds,
    ClashCount,
    EdgeCount,
    FaceCount,
    PartCount,
    Size,
    Spec,
    Tolerance,
    ValidSolid,
)
from irineval import EvalError, InspectRunner, measured_clashes, measured_facts

from irinbench.corpus import KIND_REGRESSION, Corpus, spec_id_for

#: Bounding boxes come from the exact B-rep, not a mesh, so they are
#: reproducible to far better than this. The band exists because an exact float
#: comparison would make the corpus fail on a kernel that changed its rounding
#: in the last decimal place, which is not drift worth a red run.
DEFAULT_TOLERANCE_MM = 0.01

# Why `valid_solid` is asserted rather than measured, when `clash_count` is the
# reverse.
#
# An overlap can be intentional. A press fit, a mating test fixture, a part
# modelled deliberately proud of its neighbour: recording "no part overlaps"
# would fail on models that are exactly as their author meant them.
#
# Self-intersection, an open shell and an inverted solid cannot be intentional.
# There is no design in which a body passing through itself is what was wanted.
# So soundness is asserted unconditionally, and a model that fails it fails the
# corpus until someone fixes the model.
#
# That is not a hypothetical distinction. The first full run of this corpus
# found two shipped assemblies with self-intersecting bodies. Measuring
# soundness instead of asserting it would have recorded "this model is broken"
# as the baseline and gone green forever.



def derive_spec(
    entry: str | Path,
    runner: InspectRunner,
    *,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    include_interference: bool = False,
) -> Spec:
    """Measure one artifact and record what it is as a regression spec.

    ``include_interference`` is off by default. Two reasons, and the second is
    the important one.

    It is the most expensive inspection by a wide margin: a pairwise boolean
    over every candidate pair, which on the larger assemblies here costs more
    than every other check on every other model put together.

    And what it records must be a *measurement*, not a rule. Several of these
    models overlap on purpose, a mating test fixture among them, so a baseline
    that asserted "no part overlaps" would fail by construction on the very
    models it was derived from. When enabled, the clash count is measured and
    recorded as ``clash_count``, which still catches a fourth overlap appearing
    where there were three.
    """
    entry = str(entry)
    facts = measured_facts(runner, entry)
    tolerance = Tolerance.symmetric(tolerance_mm)

    size = facts["size"]
    bounds = facts["bounds"]
    part_count = facts["part_count"]

    assertions = [
        ValidSolid(),
        Size(x=size[0], y=size[1], z=size[2], tolerance=tolerance),
        Bounds(min=bounds["min"], max=bounds["max"], tolerance=tolerance),
        PartCount(value=part_count),
        FaceCount(value=facts["face_count"]),
        EdgeCount(value=facts["edge_count"]),
    ]
    if include_interference:
        assertions.append(ClashCount(value=measured_clashes(runner, entry)))

    dims = " x ".join(f"{v:g}" for v in size)
    return Spec(
        id=spec_id_for(entry),
        prompt=(
            f"Regression baseline for {entry}. The reference model measures "
            f"{dims} mm with {part_count} part{'' if part_count == 1 else 's'}, "
            f"{facts['face_count']} faces and {facts['edge_count']} edges."
        ),
        notes=(
            "Derived by measurement, not authored from intent. These assertions "
            "record what the model already is, so it passes them by construction. "
            "This detects drift in the geometry pipeline; it does not measure "
            "whether an agent can build the right thing from a requirement."
        ),
        assertions=tuple(assertions),
    )


def derive_corpus(
    name: str,
    entries: Sequence[str | Path],
    runner: InspectRunner,
    root: str | Path,
    *,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
    include_interference: bool = False,
    on_progress=None,
) -> tuple[Corpus, tuple[tuple[str, str], ...]]:
    """Derive a spec per entry.

    Returns the corpus and the entries that could not be measured, as
    ``(entry, reason)`` pairs. A model that fails to build is reported rather
    than dropped: a corpus that silently shrinks when the engine breaks would
    hide the breakage behind a smaller, still-green run.
    """
    specs: list[Spec] = []
    bindings: dict[str, str] = {}
    failures: list[tuple[str, str]] = []
    seen_ids: dict[str, str] = {}

    for entry in entries:
        entry = str(entry)
        started = time.monotonic()
        try:
            spec = derive_spec(
                entry,
                runner,
                tolerance_mm=tolerance_mm,
                include_interference=include_interference,
            )
        except EvalError as exc:
            failures.append((entry, str(exc)))
            if on_progress:
                on_progress(entry, None, time.monotonic() - started, str(exc))
            continue

        if spec.id in seen_ids:
            failures.append(
                (entry, f"spec id {spec.id!r} already taken by {seen_ids[spec.id]}")
            )
            continue

        seen_ids[spec.id] = entry
        bindings[spec.id] = entry
        specs.append(spec)
        if on_progress:
            on_progress(entry, spec, time.monotonic() - started, None)

    corpus = Corpus(
        name=name,
        kind=KIND_REGRESSION,
        root=Path(root),
        entries=bindings,
        specs=tuple(specs),
        provenance={
            "derived_from": sorted({str(Path(e).parent) for e in bindings.values()}),
            "tolerance_mm": tolerance_mm,
            "interference_measured": include_interference,
            "entries_attempted": len(list(entries)),
            "entries_derived": len(specs),
            "entries_failed": len(failures),
        },
    )
    return corpus, tuple(failures)
