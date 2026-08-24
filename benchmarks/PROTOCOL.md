# Running the IRIN task benchmark against an agent

This is the procedure for producing a number that means something to somebody
else. It is short, and every step in it exists because skipping it makes the
result unquotable.

## Before trusting the corpus

```bash
python -m irinbench verify    # is every task satisfiable?
python -m irinbench probe     # does every task reject a wrong answer?
```

Both halves matter. A task nothing can satisfy fails an agent through no fault
of its own; a task anything satisfies measures nothing. The corpus currently
passes both.

## What is being measured

Whether an agent can turn an engineering requirement into geometry that
satisfies it. Not whether it can produce a plausible-looking model, and not
whether the file loads. Every task is scored by measuring the artifact and
comparing it to assertions written from the requirement.

## 0. Or drive the agent from here

```bash
python -m irinbench submit --out submission/ --command "<your agent>"
```

The agent is a command, not an integration: it receives one prompt on stdin and
returns source on stdout. A CLI, a curl to an API, or a shell wrapper all
satisfy that, which is what keeps the benchmark runnable against agents IRIN has
never heard of.

Nothing there judges the output. An agent that returns prose or nothing produces
exactly that, and the run scores it. Cleaning up a bad submission before
measuring it would be measuring the cleanup.

The steps below are the same thing done by hand, and are worth reading either
way.

## 1. Take the prompts

```bash
python -m irinbench prompts > tasks.txt          # or --json
```

That emits the requirements and nothing else. No assertions, no references, no
tolerances. An agent that saw those would be transcribing an answer rather than
designing to a requirement, and the resulting figure would measure retrieval.

Record the corpus fingerprint printed at the top. A result without one cannot be
compared to any other result, because a corpus name does not change when its
contents do.

## 2. Hand them to the agent

One artifact per task, all in one directory, each named after its task id:

```
submission/
  calibration-block.step.py
  circular-flange.step.py
  ...
```

`.step.py` is build123d source, which is what the CAD skill produces. `.step`
and `.stp` are accepted for an exported solid.

Give the agent whatever tooling you are measuring: the IRIN CAD skill, another
CAD library, nothing at all. That choice is part of what the number describes,
so state it when you publish.

## 3. Score it

```bash
python -m irinbench run --corpus benchmarks/tasks --artifacts submission/ \
  --agent "gemini-2.5-pro + IRIN cad skill" \
  --out benchmarks/results/<agent>-<date>.json
```

`--agent` is required and free text. Name the model version and any tooling it
was given, because those are different measurements: a model writing build123d
from memory and the same model with the CAD skill installed are not the same
system. A result that cannot name what produced it is not comparable to any
other result, and the omission becomes invisible the moment the terminal
scrollback is gone.

`--artifacts` has no default on purpose. A task corpus knows its reference
implementations, and defaulting to those would score the answer key: every task
would pass, and the run would report a perfect result measuring nothing.

## 4. Measure repair, if you want the more interesting number

```bash
python -m irinbench repair --session <id> --artifacts submission/
# hand the briefs in benchmarks/sessions/<id>/round-0-briefs/ back to the agent
python -m irinbench repair --session <id>
```

First-pass accuracy says how often an agent is right. The repair curve says
whether it can use a measurement to become right, which for engineering work
matters more. Briefs contain the requirement, the failed assertions with their
measured values, and what already passes. They contain nothing from the
reference.

## 5. Compare it to other runs

```bash
python -m irinbench compare
```

Results are grouped by corpus fingerprint and compared only within a group.
Two runs of "the tasks corpus" taken a month apart can describe entirely
different sets of tasks, and a table lining them up would manufacture a
comparison that does not exist. Runs with no fingerprint are listed apart as
unquotable rather than folded in.

## Installing the skill into the agent you are measuring

If you are measuring an agent that supports skills, give it the same tooling a
user would have:

```bash
scripts/install/install-skills.sh --agent gemini    # or codex, claude, universal
```

That symlinks this checkout's skills into the agent's skill directory, so the
agent gets the CAD workflow, the inspection CLIs and the validation policy.
State it when you publish: it is part of what the number describes.

## What to publish

State all five, or the number is not reproducible:

- the agent, including model version and any tooling it was given
- the corpus fingerprint
- the IRIN version
- first-pass rate, and the repair curve if you ran one
- the result JSON

## A conflict of interest worth naming

**The authors of this corpus should not publish the first number for it.**

The prompts here were written by the same author who built the reference
implementations. Running the benchmark against that author, or against an agent
with access to this repository, measures recall of a known answer key rather
than engineering ability, and would produce a figure that looks like a result
and is not one.

That is why no headline number appears in this repository. The machinery has
been demonstrated end to end, on a deliberately broken submission, to show the
loop works. Demonstrating that the loop works and measuring an agent are
different claims, and only the first one has been made here.

If you run this against your own agent, you are not in that position, and your
number is worth more than one produced here.
