# irineval

Geometry evaluation for [IRIN](https://github.com/nevodesigns/irin): check a
spec's assertions against real CAD geometry and return a verdict with numbers
attached.

This is the layer the project is named for. Every measurement primitive already
existed in the CAD runtime; nothing stated what an artifact *should* be and
graded what it *is*.

## Use

```python
from irinspec import Spec, Size, ValidSolid, Tolerance
from irineval import WorkerRunner, evaluate

spec = Spec(
    id="widget",
    prompt="a 40 x 25 x 8 mm block",
    assertions=(ValidSolid(), Size(x=40.0, y=25.0, z=8.0, tolerance=Tolerance.symmetric(0.05))),
)

with WorkerRunner(cwd="/path/to/project") as runner:
    result = evaluate(spec, "models/widget.step.py", runner)

print(result.summary_line())          # PASS  widget  (2/2)
for failure in result.failures():
    print(failure.detail)             # z: 8 is outside [9.9, 10.1] by -1.9 mm
```

## How it runs

The CAD kernel is reached through the `inspect` CLI in a separate process,
never imported here. A boolean that segfaults inside OpenCascade takes its own
process and the run continues, and a report generator can import this module
without installing build123d.

Inspections are deduplicated by their exact argv. Five assertions about extents,
part count and face counts all resolve to one `refs --facts` call and pay for it
once. Two interference assertions with different volume floors are genuinely
different questions and pay twice.

The `inspect` worker speaks JSONL over one persistent process, so the
OpenCascade import is paid once for a whole benchmark rather than once per
check.

## Three outcomes, not two

| Outcome | Meaning |
| --- | --- |
| pass | The assertion was checked and held |
| defect | The assertion was checked and the artifact is wrong |
| undetermined | IRIN could not establish the answer |

Undetermined is never counted as a pass and never counted as a model failure. An
inspection that crashed, a selector that did not resolve, and a dimension that is
genuinely 0.4 mm oversize are three different situations, and collapsing them
produces a benchmark that scores its own tooling breakage as model error.

`ok: false` from the CLI does **not** mean the inspection broke. Both `validate`
and `interfere` return it for a legitimately defective artifact, with `errors`
empty. The discriminator is `errors`: populated means the command could not
answer, empty means it answered and the answer is bad.

## Failure codes

`geometry_invalid`, `dimension_out_of_tolerance`, `count_mismatch`,
`interference` are defects. `inspection_failed` and `selector_unresolved` are
undetermined. Keeping them apart is what lets a later phase measure repair rates
without counting broken tooling as something an agent failed to fix.

## A note on the worker

`validate` and `interfere` reached the CLI after the worker dispatch was written
and were missing from it, so the worker answered "Unsupported inspect command"
for two of the eight assertion kinds. IRIN wires them in, and
`test_worker_integration.py` asserts the worker can answer every command the
evaluator emits, so the same gap cannot reopen silently.
