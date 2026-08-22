# irinbench

Benchmark corpora for [IRIN](https://github.com/nevodesigns/irin): derive specs
from models, run them, and report what moved.

## Two kinds of corpus, kept apart

**regression** is derived by measuring models that already exist. Every
assertion records what the geometry measures today, so a change to the CAD
engine, a dependency bump, or an accidental edit to a generator shows up as a
named dimension moving by a named amount across the whole corpus at once.

The models pass a regression corpus **by construction**. That is not a flaw, it
is what a golden master is. It is also why it cannot answer the question the
project exists to answer.

**task** states intent in a prompt and is scored on what an agent builds from
it. Its assertions come from the requirement, not from an answer, so they have
to be authored. Nothing here can derive one, and pretending otherwise would let
a green regression run be reported as evidence that an agent produces correct
geometry.

Derived specs say so in their own prompt and notes, so the two cannot be
confused later.

## Three things it does

**derive** measures existing models into a regression corpus.
**verify** checks authored tasks against references that prove them buildable.
**repair** runs a turn-based session and reports how much feedback helps.

## Use

```bash
# Measure the curated models and write a regression corpus
python -m irinbench derive --name regression

# Run it
python -m irinbench run

# Summarize a stored result
python -m irinbench report benchmarks/results/<file>.json
```

`run` exits non-zero when the corpus does not fully pass, so CI can gate on it.

Layout:

```
benchmarks/
  regression/
    corpus.json        kind, spec-to-artifact bindings, provenance
    specs/<id>.json    one spec per model
  results/
    <name>-<time>.json one run
```

The binding between a spec and an artifact lives in the manifest, not inside the
spec. A regression spec is bound to a model; a task spec is not bound to
anything, because the agent has to produce it. Keeping `Spec` free of a path is
what lets one object serve both.

## What a run reports

```
  specs        48 / 51   ############################.....   94.1%
  assertions  302 / 312  ##############################...   96.8%
  specs with undetermined  1 (2 assertions could not be established)
```

Three numbers, not one. Specs passing, assertions passing, and how many could
not be established at all. A run with twenty undetermined assertions has a
tooling problem rather than a geometry problem, and a single score cannot tell
you which.

The failure taxonomy is printed alongside, because the shape of a run matters
more than its score. Thirty dimension misses is a modelling problem; thirty
inspection failures is a broken toolchain, and the single percentage is
identical in both cases.

## Tolerance

Bounding boxes come from the exact B-rep rather than a mesh, so they reproduce
far tighter than the default 0.01 mm band. The band exists so the corpus does
not go red because a kernel changed its rounding in the last decimal place,
which is not drift worth failing a run over.
