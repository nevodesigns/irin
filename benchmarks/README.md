# IRIN benchmarks

Spec corpora and stored results. Source-only: the runner lives in
`packages/irinbench` and reads this from a checkout, and nothing under `skills/`
touches it. The publish step trims this directory.

```bash
python -m irinbench derive --name regression   # measure the models, write the corpus
python -m irinbench run --timeout 120          # score it, write a result file
python -m irinbench report benchmarks/results/<file>.json
```

## tasks

22 requirements written from engineering intent, each with assertions written
from the requirement. This is the corpus that answers the question IRIN exists
for: can an agent turn a sentence into correct geometry?

Seventeen are single parts. Five are assemblies, which is where agents struggle
and where `part_count`, `no_interference` and `feature_spacing` earn their
place: a planetary stage whose three planet bores sit on an 84 mm circle, a
shock absorber specified by its 340 mm eye-to-eye length, an iris with twelve
pivots on one circle and six fixings on another.

Interference is asserted only where the design requires it. Meshing gears,
press fits and treads let into a column all overlap on purpose, so a task
demanding zero clashes would fail assemblies that are exactly right. The
propeller asserts it, because no blade may intersect another.

```bash
python -m irinbench verify                       # are the tasks themselves sound?
python -m irinbench run --corpus benchmarks/tasks --artifacts <dir>
```

`--artifacts` is required and has no default. A task corpus knows only its
reference implementations, and defaulting to those would score the answer key:
every task would pass and the run would report a perfect result measuring
nothing. Name one file per task id, `<task-id>.step.py`, `.step` or `.stp`.

A task that produced no artifact scores as `artifact_missing`, counted as a
defect rather than undetermined. An agent given a prompt and returning nothing
has failed, and calling that inconclusive would let the worst outcome report as
the mildest. Runs report the count on its own line, because forty parts built
badly and none built at all are different results.

### Repair sessions

Generating correct geometry first time is one capability. Reading a failure
report and fixing the thing is a different one, and for engineering work it is
the more important of the two.

```bash
python -m irinbench repair --session <id> --artifacts <dir>   # round 0
# revise the artifacts using the briefs, then:
python -m irinbench repair --session <id>                     # round 1, 2, ...
```

Turn based, because IRIN cannot invoke arbitrary agents and tying the benchmark
to whichever one it happened to support would make the number less portable, not
more. IRIN scores, writes one brief per failing task, and stops. The operator's
agent revises. IRIN scores again.

A brief carries the original requirement, the assertions that failed with their
measured values, and the assertions that already pass and must keep passing. It
carries **nothing** from the reference implementation, because leaking it would
turn repair into transcription.

That last list is not padding. A repair that fixes what was reported and breaks
what was not is a real and common outcome, and a loop counting only recoveries
would score it as progress. Regressions are tracked and reported per round.

The result is the table this project was built to produce:

```
  first pass                   3    17.6%
  recovered after 1 repair     2    11.8%
  unrecovered                 12    70.6%

  final 29.4% (from 17.6% before any feedback)
```

Sessions live under `benchmarks/sessions/<id>/` and are not committed by
default: a session is one agent's working history, not a published result.

### Verification

Every task carries a reference implementation it was **not** derived from, and
`verify` checks the task against it. This is what separates a benchmark from a
wishlist. A spec authored from intent can be unsatisfiable ("six 30 mm holes on
a 60 mm bolt circle") or simply wrong about its own geometry, and nothing in the
schema would object. An agent scored against such a task fails through no fault
of its own, and the run reports an author's mistake as a model weakness.

All 17 currently verify. Three did not when first written, and each failure was
the spec being less precise than the part:

- the clevis has two aligned 14 mm bores, one per ear, not one
- the pulley's vee groove divides its 70 mm rim into two flanges
- relieving the gear hub on both faces leaves two hub rings

In every case the prompt and the assertion were corrected together to describe
what the part really is. Tuning numbers until a spec passes would defeat the
purpose; the point is that verification found the imprecision.

## regression

51 curated models, from `models/step/parts` (32) and `models/step/assemblies`
(19). Each spec records what its model measures: soundness, extents, bounds,
part count, face count, edge count.

This detects drift in the geometry pipeline. It does not measure whether an
agent can build the right thing from a requirement. That needs a `task` corpus,
whose prompts and assertions are authored from intent rather than read off an
answer, and nothing can derive one.

### Current baseline: 46 of 51

`benchmarks/results/regression-baseline.json`, IRIN 0.4.20, 816 s.

```
  specs         46 / 51    90.2%
  assertions   301 / 306   98.4%
```

The five that do not pass are known, and each is a finding rather than noise.

**Two genuine defects.** `mars_rover_concept` and `pelican_riding_bicycle` ship
with self-intersecting bodies: `terrain_rock_03`, `terrain_rock_08`,
`pelican_round_body`, `left_eye`, `right_webbed_foot_on_rear_pedal`. A body
passing through itself cannot be intentional, so these stay red until the models
are fixed. They were inherited in this state.

**Three timeouts.** `cutaway_turbofan_engine`, `flying_car` and
`sculpted_humanoid` exceed 120 s inside a single `validate` call. They are
reported as undetermined, never as defects: IRIN could not establish the answer,
which is a different fact from the answer being bad. Raise `--timeout` to score
them, at the cost of a much longer run. One of these held the CPU for over
twenty minutes before the budget existed.

Do not re-derive to make a failure disappear. Re-deriving overwrites the
baseline with whatever the pipeline now produces, which turns a caught
regression into a silently accepted one. Re-derive only when a model changed on
purpose.

## Cost

The 51-model run takes about 14 minutes on one machine, and the assemblies
dominate it. Interference is off by default when deriving because it is the most
expensive inspection by a wide margin; enable it with `derive --interference`,
which records the clash count each model actually has rather than asserting it
has none.
