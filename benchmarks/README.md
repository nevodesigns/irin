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
| gemini-3.6-flash, no CAD skill (PARTIAL, 19 of 28) | 8 / 19 (42.1%) | 57 / 105 (54.3%) |
| gemini-3.6-flash, CAD skill refs in context (PARTIAL, same 19) | 7 / 19 (36.8%) | 56 / 105 (53.3%) |
| gemini-2.5-flash, no CAD skill (PARTIAL, 21 of 28) | 8 / 21 (38.1%) | 66 / 115 (57.4%) |
| nvidia/nemotron-3-super-120b-a12b via OpenRouter, no CAD skill | 7 / 28 (25.0%) | 61 / 149 (40.9%) |
| nvidia/nemotron-3-ultra-550b-a55b via OpenRouter (PARTIAL, 22 of 28) | 4 / 22 (18.2%) | 37 / 116 (31.9%) |
| openai/gpt-oss-120b via Groq, no CAD skill | 3 / 28 (10.7%) | 20 / 149 (13.4%) |
| qwen/qwen3.8-27b via Groq (PARTIAL, 23 of 28) | 0 / 23 | 4 / 123 (3.3%) |
| openai/gpt-oss-20b via Groq (PARTIAL, 21 of 28) | 0 / 21 | 0 / 115 |
| qwen2.5-3b-instruct q4_K_M, local, no CAD skill | 0 / 28 | 0 / 149 |

None has a CAD skill installed, so these measure what a model knows about
build123d unaided. None is flattering, and that is the point of having a scale
that starts at the bottom.

The Gemini row is partial and will stay that way. Its seven missing tasks were
lost to a quota, and by the time the quota reset the model had been withdrawn:
`gemini-2.5-flash` is no longer served to new API keys. The run cannot be
finished, by anyone, ever.

That is worth stating as a general fact about this kind of benchmark rather than
as a footnote about one row. A result is a measurement of a model at a moment,
and the model is the part that expires. An unfinished run is not a task you can
come back to at your convenience: the window in which it can be completed is
the vendor's to close, and they close it without notice. Finish a run in one
sitting where the quota allows it.

A further run is not in the table at all. qwen3.6-27b got five of twenty-eight
tasks past the same token cap, scored 0 of 5, and that is not a measurement of
anything. The result file is kept and `audit` flags it as a thin sample, because
the honest thing is to record that the run happened rather than to quote a
percentage over a fifth of the corpus, chosen by a rate limiter rather than by
design.

**The two partial rows are not comparable to the full ones.** Gemini answered 21
of 28 before its quota ran out; the 550B model was refused six requests by the
free tier. Those tasks were never put to either model, so they are excluded
rather than counted as failures, and the percentage is over a smaller and
differently chosen set. They are listed because the numbers are worth knowing,
not because they can be set beside a complete run.

**The 550B model scores below its 120B sibling**, on assertions as well as
specs, and assertion rate is the fairer of the two here because it does not
depend on which tasks each was asked. It is one observation on one corpus with
no CAD skill in play, so it is not a claim about scale in general. What it does
show is that the thing being measured is not something a bigger model gets for
free: knowing that `Cylinder` takes `radius` and not `diameter` is recall of a
specific library, and there is no reason parameter count should supply it.

The 3B local model does not know the library at all. Across 28 tasks it
produced 45 distinct failures and invented most of the API it used: `make_box`,
`create_part`, `create_context`, a private `_b3d` import, `center=` on `Box`.
Its 0/28 is now measured on clean artifacts, with no fence markers and no
echoed prompt, so it stands as a real floor rather than an adapter's. The larger models write recognisable build123d and still fail on real API
mistakes: `Cylinder(diameter=...)` where the parameter is `radius`, `.rotate()`
on a `Location`, `.z` on a `Vector`, `Polyline` inside a `BuildSketch` where it
belongs to `BuildLine`.

The two Gemini rows are a year apart and land in the same place: 8 specs each,
42.1% against 38.1%, on overlapping but not identical subsets. Neither is
complete, so the gap is not worth reading as progress. What is worth reading is
that a generation of model development moved this number very little, while the
failures stayed the same kind.

One mistake shows up at the top of the failure list for four separate models
from three vendors: passing the wrong keyword to `Cylinder`. build123d wants
`radius`, and models reach for `diameter` or `r`. gpt-oss-20b, gpt-oss-120b and
qwen3.8-27b each lose more assertions to that single argument name than to
anything else.

That is the clearest evidence here that the corpus is measuring what it set out
to. A model failing on `Cylinder(diameter=...)` has understood the requirement,
chosen the right primitive, and got the parameter name wrong. It is not
confused about the engineering. It is missing one fact about one library, which
is exactly the kind of gap a skill supplies and a larger model does not.

Every one of them is held up by the same thing, and it is not reasoning about
geometry. It is knowing the actual signatures of a library. Gemini is ahead of
the two 120B models on the tasks it attempted, and its failures are the same
kind, just fewer. That gap is what a CAD skill closes, and measuring the unaided
floor first is what makes the aided number mean something later.

Nemotron fails two tasks by never writing code at all. It reasons about the
clevis bracket and the L bracket at length, runs out of budget, and stops. Those
score as defects, and they are its own result rather than an adapter fault: the
decode step recovers reasoning-then-code everywhere the code exists, and in
these two replies it does not exist.

### Putting the skill's documentation in front of a model changed nothing

The first controlled pair on this corpus: one model, one set of nineteen tasks,
one adapter, and the only difference is roughly 13,000 tokens of the CAD skill's
reference documentation ahead of each prompt. This is not an agent with the
skill installed, which could run `inspect` and fix what it built. It is one shot
with the manual open, which measures what the written guidance is worth alone.

It is worth nothing here, and slightly less than nothing: 7 of 19 against 8.

The net is not the interesting part, because it is smaller than the churn. Two
tasks were gained, three were lost, five kept. A single pair of runs against a
model sampling at its default temperature cannot separate a small effect from
run-to-run variance, and this corpus at 19 tasks does not have the resolution to
try. Repeat runs at one setting would be needed to say anything about an effect
this size, and none have been done.

What is diagnosable is why it could not have helped. This model's largest single
failure, by some margin, is `Locations doesn't accept type PolarLocations`. The
three references sent name `Cylinder` four times and `Locations` not once. The
documentation does not cover the API the model actually gets wrong.

So the honest reading is narrow. Reference text did not close the gap for this
model, because the text and the gap are about different things. It says nothing
about what an installed skill does, and nothing yet about whether documentation
that addressed the real failure would help.

**The benchmark found a hole in the product.** `PolarLocations` is how bolt
circles are placed, several tasks in this corpus need them, and the modelling
reference is silent. That gap was invisible until something was scored against
it, which is the whole argument for having a corpus authored from intent.

Filling it is deliberately not done here. Editing the reference material to move
a number this repository publishes is the conflict of interest
[PROTOCOL.md](PROTOCOL.md) warns about, and doing it in the same change that
reports the finding would make the finding unreadable.

### Every number here was wrong before it was right

Not one of these figures survived contact with its own harness. Nemotron went
0/28, then 4/28, then 7/28 without the model changing at all:

```
  0 / 28   one unreadable file was hiding the other 27
  4 / 28   discovery fixed; the file itself was still mis-decoded
  7 / 28   decoding fixed: an unbalanced fence, and reasoning written out as code
```

Two bugs, both in this repository, both costing the model points it had earned.
gpt-oss-120b moved 0/28 to 3/28 for the first reason alone.

The local model is the case worth studying. It was hit by exactly the same bug
and its number did not move: 0/28 before, 0/28 after. All 149 of its assertions
had carried the same fabricated reason, and the total those reasons summed to
was right anyway. Had it been the only run, nothing in the output would have
looked wrong, and the bug would still be here.

A wrong number announces itself eventually. A right number reached the wrong way
does not. That is why both fixes are pinned by tests rather than by anyone
having noticed, and why the decode step now ships as `irinbench extract` instead
of living in whatever adapter each person writes. See the note under `submit`,
and the adapter section of [PROTOCOL.md](PROTOCOL.md).

**A benchmark's own robustness is part of the measurement.** A harness that is
fragile against bad input does not report a low score. It reports zero, for
everyone, and zero looks exactly like a model that cannot do the task.

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
