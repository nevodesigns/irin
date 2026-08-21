# IRIN benchmarks

Spec corpora and stored results. Source-only: the runner lives in
`packages/irinbench` and reads this from a checkout, and nothing under `skills/`
touches it. The publish step trims this directory.

```bash
python -m irinbench derive --name regression   # measure the models, write the corpus
python -m irinbench run --timeout 120          # score it, write a result file
python -m irinbench report benchmarks/results/<file>.json
```

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
