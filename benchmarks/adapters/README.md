# Adapters

An agent that answers over HTTP does not return a file. It returns a reply, and
the CAD source is somewhere inside it. The code that turns one into the other is
the adapter, and `submit` runs it once per task: prompt on stdin, source on
stdout.

Every adopter of this benchmark has to write that, which is why a working one
ships here instead of being left as an exercise.

```bash
export IRIN_API_BASE=https://api.groq.com/openai/v1
export IRIN_API_KEY_FILE=~/.groq-key
export IRIN_API_MODEL=openai/gpt-oss-120b

python -m irinbench submit --corpus benchmarks/tasks --out ./submission \
    --command "$PWD/benchmarks/adapters/openai_compatible.py"
```

Groq, OpenRouter, Cerebras, Together and most other providers speak the same
protocol, so `IRIN_API_BASE` and `IRIN_API_MODEL` are the only things that
change between them.

| variable | meaning |
| --- | --- |
| `IRIN_API_BASE` | endpoint root, without `/chat/completions` |
| `IRIN_API_MODEL` | model id as the provider spells it |
| `IRIN_API_KEY_FILE` | file holding the key, preferred |
| `IRIN_API_KEY` | the key itself, if you have no file |
| `IRIN_API_MAX_TOKENS` | budget, default 4000 |
| `IRIN_API_DELAY` | seconds to wait before each request, default 0 |
| `IRIN_API_TIMEOUT` | seconds to wait for a reply, default 240 |
| `IRIN_REASONING_EFFORT` | passed through to models that accept it |

Standard library only, and it must stay that way. `submit` runs the command
through a shell, so the interpreter is whatever `/usr/bin/env python3` finds on
your PATH, which is very often not the environment IRIN is installed into. The
adapter loads `extract` and `transport` by file path for the same reason:
importing the `irinbench` package would pull in the corpus loader and through it
`irinspec`, and neither is needed to decode a chat reply.

**Give `--command` an absolute path.** The command runs with its working
directory set to the submission folder, so a relative path resolves against that
and the shell cannot find it.

Reading the key from a file is preferred because an environment variable is
visible to anything that can list processes.

## Why this is not a trivial script

Three versions of this file in this repository each published a number that was
too low, and none of them looked wrong at the time.

**An unbalanced fence.** A reply cut off at the token limit has an opening
```` ``` ```` and no closing one. Writing that into the artifact turns valid
source into a `SyntaxError`, and until recently one unreadable file could hide
every other file in the directory from the scorer.

**Reasoning written out as code.** A model deliberated for fifty-four lines and
then wrote a correct generator. The whole reply went to disk and the task scored
zero. A model that marks its thinking with `<think>` is a harder case than it
looks: it drafts an import inside the block, reconsiders, and writes a different
one below, so a naive search for the first import finds the draft it discarded.

**An error envelope nobody read.** Providers disagree about where an error goes.
OpenAI nests it under `error`; others put `message` at the top level. A billing
wall arrived in the second shape, the adapter found no error and no choices, and
scored it as a model that answered with nothing.

The decoding lives in `irinbench.extract` and the error classification in
`irinbench.transport`, both tested against the exact replies real models
produced. If you write your own adapter, import those two rather than
reimplementing them.

## The one thing you must get right

**Exit 75 when the question never reached the model.**

`submit` keys its NEVER ASKED list on that exit code. A rate limit, an expired
key, an unpaid invoice or a dropped connection all mean the model was never
asked, and those tasks must not be scored. A model that returns nothing has
answered, and scores as a failure; a model that could not be reached has not,
and scoring it as a failure publishes somebody's rate limiter as a modelling
weakness.

Getting this backwards is the single most consequential adapter bug, because
the result still looks entirely reasonable.

## Rate limits

Two kinds, and they truncate a run differently.

**Per-minute** limits are paceable. Raise `IRIN_API_DELAY` until requests stop
being refused. Token-metered providers are the awkward case: a 6000-token
request needs 6000 tokens of headroom, so the wait is set by the budget
refilling rather than by any fixed interval.

**Per-day** limits are not paceable at all. OpenRouter's free tier allows 50
model requests a day, which is under two full passes of a 28-task corpus. Plan a
sweep of several models around that, or the later ones score nothing for a
reason that has nothing to do with them.

Either way, check coverage before quoting a number:

```bash
python -m irinbench audit benchmarks/results/<file>.json
```
