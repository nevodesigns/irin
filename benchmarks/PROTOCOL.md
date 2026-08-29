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

### Decoding the reply is the adapter's job, and it is where the bugs are

A chat model does not return a file. It returns a reply, and the source is
somewhere inside it. Getting that wrong is the single most likely way to publish
a number that is too low, and it does not look like a bug from the outside: it
looks like a model that cannot write build123d.

```bash
your-agent | python -m irinbench extract
```

This repository got that step wrong three times against real models, and each
one cost a published figure:

- A reply cut off at the token cap kept its opening fence and lost its closing
  one. The stray ` ``` ` went into the file and made valid source a syntax error.
- Another arrived with a closing fence and no opening one, with the same result.
- One model wrote fifty-four lines of reasoning and then a correct generator.
  The whole reply was written out, and the task scored zero.

The rule that resolves all three: **framing is yours, content is the model's.**
A markdown fence, a prompt your local runner echoed back, reasoning emitted
before the answer, none of those are the model's attempt at the requirement.
Writing them into the artifact scores your transport instead of its engineering.

The line is drawn at whether source is present, never at whether it is any good.
`extract` never repairs, completes or tidies code, and a reply holding no source
stays a failure: it exits 1 and writes nothing. A model that spent its whole
budget thinking and never wrote code has not answered, and must score as not
having answered.

Give reasoning models a real token budget. A truncated part is indistinguishable
from an incompetent one in the result file, and the difference is yours to
remove, not the model's.

### And check what the provider is actually rating

A budget generous enough for a reasoning model can be larger than the provider
allows per minute, and the request is then rejected before the model ever sees
it. Groq's free tier meters **tokens**, 8000 a minute against 1000 requests, so a
`max_tokens` of 12000 failed every call as too large while the request counter
sat at 971 remaining. Twelve of twenty-eight tasks were never asked, and the
cause was a number chosen to be helpful.

Read the limit off the response headers rather than assuming which one binds:

```bash
curl -sD - -o /dev/null https://<provider>/chat/completions ... | grep -i ratelimit
```

Pace to the metered resource. If the cap is 8000 tokens a minute and a reply may
use 6000, the corpus takes about one request every 45 seconds, and a run that
tries to go faster spends its budget on rejections.

Daily caps are a separate thing again and cannot be paced around. OpenRouter's
free tier allows 50 model requests a day, which is under two full passes of this
28-task corpus. Plan a sweep of several models around that, or the later ones
score nothing for a reason that has nothing to do with them.

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

For an agent behind an HTTP API, `benchmarks/adapters/` has a working adapter
for any OpenAI-compatible endpoint, which covers Groq, OpenRouter, Cerebras,
Together and most others:

```bash
export IRIN_API_BASE=https://api.groq.com/openai/v1
export IRIN_API_KEY_FILE=~/.groq-key
export IRIN_API_MODEL=openai/gpt-oss-120b

python -m irinbench submit --corpus benchmarks/tasks --out ./submission \
    --command "$PWD/benchmarks/adapters/openai_compatible.py"
```

It ships because every adopter has to write this and it is where the bugs live.
Three versions of it here each published a number that was too low: an
unbalanced code fence that turned valid source into a SyntaxError, a model whose
reasoning was written to disk as though it were code, and a billing wall in an
error envelope the adapter did not read. Read
[adapters/README.md](adapters/README.md) before writing your own, and import
`irinbench.extract` and `irinbench.transport` rather than reimplementing them.

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

## 4. Audit the result before you quote it

```bash
python -m irinbench audit benchmarks/results/<file>.json
```

This does not check whether a score is good. It checks whether the result looks
like it came from measuring every task separately, which is a different question
with a checkable answer.

Every scoring bug this project has shipped was caught by someone finding a
number surprising and going digging. That is not a detection mechanism, because
it needs the number to be surprising. The worst case here was a 3B model scoring
0/28 through a bug that fabricated all 149 of its failure reasons, and 0/28 is
what a 3B model scoring honestly would have got. Nothing about it looked wrong.
It came to light only because a larger model was broken by the same bug into a
number that did look wrong.

A harness that breaks tends to break identically everywhere, so it leaves a
signature in how the failures are distributed even when the total is plausible.
`audit` looks for that signature: one reason reported as every reason, too few
distinct reasons for the number of failing specs, and a subset scored as though
it were the whole corpus.

Findings are suspicions, not verdicts. A model can genuinely fail every task the
same way, and each finding says what would settle it. Confirm before discarding
a number, and confirm before publishing one.

The steps below are the same thing done by hand, and are worth reading either
way.

## 5. Measure repair, if you want the more interesting number

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

## 6. Compare it to other runs

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
