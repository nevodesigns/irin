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

28 requirements written from engineering intent, each with assertions written
from the requirement. This is the corpus that answers the question IRIN exists
for: can an agent turn a sentence into correct geometry?

Twenty-three are single parts. Five are assemblies, which is where agents
struggle and where `part_count`, `no_interference` and `feature_spacing` earn
their place: a planetary stage whose three planet bores sit on an 84 mm circle,
a shock absorber specified by its 340 mm eye-to-eye length, an iris with twelve
pivots on one circle and six fixings on another.

### Written first, or found afterwards

Twenty-two tasks were reverse-engineered from models already in this
repository. That is a legitimate way to build a corpus and it carries a quiet
bias: only requirements the existing parts happened to satisfy could be
written.

Six were done the other way round. The requirement was fixed first, from
engineering practice, and a reference was then built to satisfy it: a NEMA 17
motor mount, a flanged shaft coupling, a pillow block, a vee block, a headed
drill bushing, a six-hole spacer ring. All six verified on the first attempt,
which is evidence the vocabulary can express a requirement chosen
independently rather than only describe geometry that already exists.

The vee block is the one task that asserts the *absence* of a feature. It has
no holes, and a model that added one would fail.

Interference is asserted only where the design requires it. Meshing gears,
press fits and treads let into a column all overlap on purpose, so a task
demanding zero clashes would fail assemblies that are exactly right. The
propeller asserts it, because no blade may intersect another.

```bash
python -m irinbench prompts                      # what you hand to the agent
python -m irinbench verify                       # are the tasks themselves sound?
python -m irinbench run --corpus benchmarks/tasks --artifacts <dir> --agent "<what produced them>"
python -m irinbench compare                      # results side by side
```

**[PROTOCOL.md](PROTOCOL.md) is the procedure for running this against your own
agent and publishing a number somebody else can use.** Read it before quoting a
figure from here.

`prompts` emits the requirements and nothing else: no assertions, no references,
no tolerances. An agent that saw those would be transcribing an answer rather
than designing to a requirement.

`--artifacts` is required and has no default. A task corpus knows only its
reference implementations, and defaulting to those would score the answer key:
every task would pass and the run would report a perfect result measuring
nothing. Name one file per task id, `<task-id>.step.py`, `.step` or `.stp`.

A task that produced no artifact scores as `artifact_missing`, counted as a
defect rather than undetermined. An agent given a prompt and returning nothing
has failed, and calling that inconclusive would let the worst outcome report as
the mildest. Runs report the count on its own line, because forty parts built
badly and none built at all are different results.

### What the prompts say and what is checked

A prompt may contain a requirement the vocabulary cannot yet check. The
calibration block asks for a 2 mm top chamfer, and nothing measures chamfer
size, so an agent that omitted it would still pass that task.

Those clauses stay in the prompts. Removing them would make the requirements
artificially thin and less like real engineering language, and the gap is
better stated than hidden. Chamfer size, wall thickness and draft angle are the
current ones.

An unchecked clause can leave a task vacuous, and one was. The vee block asked
for a 90 degree groove and asserted size, bounds, part count and no holes, all
of which a plain 60 mm cube satisfies. A stand-in agent returned exactly that
and passed. It now asserts volume, 192000 mm^3 against a cube's 216000, so the
groove is checked by the material it removes.

The lesson generalises: when a prompt asks for material to be taken away or
added and nothing measures it, assert `volume`. It is the only check that sees
a change a bounding box cannot.

### Published results

```bash
python -m irinbench compare
```

| agent | specs | assertions |
| --- | --- | --- |
| nvidia/nemotron-3-super-120b-a12b via OpenRouter, no CAD skill | 4 / 28 (14.3%) | 38 / 149 (25.5%) |
| openai/gpt-oss-120b via Groq, no CAD skill | 3 / 28 (10.7%) | 20 / 149 (13.4%) |
| qwen2.5-3b-instruct q4_K_M, local, no CAD skill | 0 / 28 | 0 / 149 |

All three are complete runs with no CAD skill installed, so they measure what a
model knows about build123d unaided. None is flattering, and that is the point of
having a scale that starts at the bottom.

The 3B local model does not know the library at all: it writes `make_box` where
build123d has `Box`, passes `size=` to `Box`, and tries to import a private
module. The two 120B models write recognisable build123d and still fail most
tasks on real API mistakes: `Cylinder(diameter=...)` where the parameter is
`radius`, `.rotate()` on a `Location`, `.z` on a `Vector`.

Every one of the three is held up by the same thing, and it is not reasoning
about geometry. It is knowing the actual signatures of a library. That gap is
what a CAD skill closes, and measuring the unaided floor first is what makes the
aided number mean something later.

Nemotron also failed three tasks by returning prose instead of code. It wrote out
its reasoning, the file did not parse, and those three score as defects. That is
its own result and not an adapter fault: the same adapter carried its other
twenty-five answers.

**The first version of every number here was scored against a bug**, and finding
out why was worth more than the numbers. One malformed file in a submission was
hiding all the others, so gpt-oss-120b first scored 0/28 rather than 3/28, and
Nemotron 0/28 rather than 4/28.

The local model is the case worth studying. It was poisoned in exactly the same
way, and its number did not move: 0/28 before, 0/28 after. Every one of its 149
assertions had carried the same fabricated reason, and the total those reasons
added up to happened to be right. Had that been the only run, nothing about the
output would have looked wrong, and the bug would still be here.

A wrong number announces itself eventually. A right number reached the wrong way
does not, which is why the fix is enforced by tests rather than by having
noticed. See the note under `submit`.

The authors of this corpus have not published a result for it and should not.
See [PROTOCOL.md](PROTOCOL.md).

### Partial runs and agents that cannot be reached

A rate-limited API makes an interrupted run ordinary rather than exceptional.
Two things keep that from being reported as model failure.

`submit` separates an agent that **answered with nothing** from one that could
not be **asked at all**. An adapter exits 75 for a rate limit, an expired key or
a network failure, and those tasks are listed under NEVER ASKED with a warning
against scoring the submission as it stands.

`run --only <ids>` scores the tasks that were actually attempted, and marks the
result partial. A partial result records how many tasks the corpus holds, prints
a PARTIAL banner, and is labelled as such in `compare`, so it can never be read
as a full run.

Both exist because the first real agent run hit a free-tier quota two thirds of
the way through. Without them, eight tasks the model never saw would have scored
as eight failures by the model.

### One bad file may not speak for the directory

A submission is a directory of files written by something that does not always
write code. Nemotron returned its reasoning as prose for three tasks. A local
model produced a file with an unmatched bracket. This is normal and the scoring
must survive it.

It did not, twice. Discovery walks the whole directory to resolve one target, and
a single unreadable file aborted the walk, so every task in the submission came
back as "ref not found". Both 120B models first scored 0/28 that way, and both
numbers looked plausible enough to publish.

The first fix named the exception types it had seen. The second bad file raised a
different one and the bug came back unchanged. So the guard is no longer a list
of types:

```python
except Exception:  # noqa: BLE001
    # nothing wrong with some other file may decide the answer to
    # "where is this target"
```

Enumeration stays strict. Asking "what is in this tree" must still fail loudly on
a tree that is broken, because that question is asked by an author about their own
work. Resolving one known path is the resilient half, and only that half. Both
directions are held by tests.

The general rule, which cost two shipped bugs to learn: **a benchmark's own
robustness is part of the measurement.** A scoring harness that is fragile in the
presence of bad input does not report a low score. It reports zero, for everyone,
and zero looks exactly like a model that cannot do the task.

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

The result is the table this project was built to produce. This one is a shape,
not a result: it came from a deliberately broken submission against the corpus
as it stood at 17 tasks, and it demonstrates that the loop works rather than
measuring anyone's CAD ability.

```
  first pass                   3    17.6%
  recovered after 1 repair     2    11.8%
  unrecovered                 12    70.6%

  final 29.4% (from 17.6% before any feedback)
```

See [PROTOCOL.md](PROTOCOL.md) before producing one of these for real, and in
particular the section on why the authors of this corpus should not publish the
first number for it.

Sessions live under `benchmarks/sessions/<id>/` and are not committed by
default: a session is one agent's working history, not a published result.

### Verification

Every task carries a reference implementation it was **not** derived from, and
`verify` checks the task against it. This is what separates a benchmark from a
wishlist. A spec authored from intent can be unsatisfiable ("six 30 mm holes on
a 60 mm bolt circle") or simply wrong about its own geometry, and nothing in the
schema would object. An agent scored against such a task fails through no fault
of its own, and the run reports an author's mistake as a model weakness.

All 28 currently verify. Three did not when first written, and each failure was
the spec being less precise than the part:

- the clevis has two aligned 14 mm bores, one per ear, not one
- the pulley's vee groove divides its 70 mm rim into two flanges
- relieving the gear hub on both faces leaves two hub rings

In every case the prompt and the assertion were corrected together to describe
what the part really is. Tuning numbers until a spec passes would defeat the
purpose; the point is that verification found the imprecision.

### Are the tasks strong enough to be worth failing?

```bash
python -m irinbench probe
```

`verify` proves a task is satisfiable and cannot see the opposite failure: a
task whose assertions are loose enough that wrong answers pass. The reference
passes either way, so verification is blind to it.

`probe` asks the other half. Every task is given the most charitable wrong
answer available, a sound solid with the reference's own bounding size and no
features at all, and must reject it. A task that passes is checking extents and
calling them a requirement.

All 28 reject it, and the report names which assertion did the rejecting, so an
author can see what is carrying each task:

```
  ok    nema17-motor-mount   rejected by bolt_circle, fillet_count, hole_count
  ok    pillow-block         rejected by feature_spacing, hole_count
  ok    vee-block            rejected by volume
  ok    stepped-shaft-keyway rejected by boss_count
```

That last one is worth noticing. `stepped-shaft-keyway` is held up by a single
assertion, so it is the thinnest task in the corpus and the first to strengthen.

This exists because the vee block was vacuous and nothing caught it. A stand-in
agent returned a plain cube and passed a task asking for a 90 degree groove. The
accident that found it is not a method; this is.

### Every result names the corpus that produced it

A corpus has a fingerprint: a content hash over its specs. It is recorded in the
manifest, carried in every result file, and printed at the top of `prompts`.

Without it, two results both claiming corpus `tasks` could have been scored
against entirely different requirements and nobody comparing them would know. A
name cannot serve, because names do not change when content does.

Hashed over the specs alone, not the references. References decide whether a
task is *sound*; specs decide what an agent is *scored on*, and only the second
belongs in a number's identity. Editing a spec on disk without re-saving the
corpus is caught on load, rather than silently producing results that name the
wrong requirements.

Current: tasks `74bfef8abe3e` (28), regression `b38208d40d27` (57).

`compare` groups stored results by fingerprint and compares only within a group.
A run that records no agent falls back to its filename, which is worse than a
name and far better than a blank row.

## regression

57 curated models, from `models/step/parts` (38) and `models/step/assemblies`
(19). Each spec records what its model measures: soundness, extents, bounds,
part count, face count, edge count.

This detects drift in the geometry pipeline. It does not measure whether an
agent can build the right thing from a requirement. That needs a `task` corpus,
whose prompts and assertions are authored from intent rather than read off an
answer, and nothing can derive one.

### Current baseline: 52 of 57

`benchmarks/results/regression-baseline.json`, IRIN 0.4.20, corpus
`b38208d40d27`, 861 s.

```
  specs         52 / 57    91.2%
  assertions   337 / 342   98.5%
```

The corpus grew from 51 when six references were added for new tasks.
Re-deriving changed no existing baseline: all 51 earlier models measured
byte-identical, which is worth knowing on its own, because it means the geometry
pipeline is reproducible and a future difference is real drift rather than
noise. All six new models pass.

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
