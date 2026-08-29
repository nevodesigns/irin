#!/usr/bin/env python3
"""Ask an OpenAI-compatible chat endpoint for one task, and print the source.

Every adopter of this benchmark has to write this, and it is where the bugs
live. Three separate versions of it in this repository each published a number
that was too low, and none of them looked wrong:

  - an unbalanced code fence, left in the artifact, turned valid source into a
    SyntaxError
  - a model that reasoned for fifty-four lines before writing a correct
    generator had the whole reply written to disk
  - a payment wall arrived in an envelope the adapter did not read, and scored
    as a model that answered with nothing

So it ships here rather than being left as an exercise. Groq, OpenRouter,
Cerebras, Together and most others speak this protocol, so one file serves all
of them and the benchmark stays provider-agnostic.

Standard library only, so it runs wherever Python does. The decoding and the
error classification come from `irinbench`, where they are tested against the
exact replies real models produced.

    export IRIN_API_BASE=https://api.groq.com/openai/v1
    export IRIN_API_KEY_FILE=~/.groq-key
    export IRIN_API_MODEL=openai/gpt-oss-120b
    python -m irinbench submit --corpus benchmarks/tasks --out ./submission \\
        --command benchmarks/adapters/openai_compatible.py

Contract, per `irinbench submit`: one task prompt on stdin, CAD source on
stdout, nothing else on stdout. Exit 75 when the question could not be asked at
all, so an outage is recorded as an outage rather than as a failure by the model.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_IRINBENCH = (
    Path(__file__).resolve().parents[2] / "packages" / "irinbench" / "src" / "irinbench"
)


def _load(module: str):
    """Load one irinbench module without importing the package.

    `import irinbench.extract` runs the package __init__, which pulls in the
    corpus loader and through it irinspec, and neither is needed to decode a
    chat reply. That chain is also why the adapter has to be careful about which
    interpreter runs it: a bare `python3` on PATH may be any environment at all,
    and this one only needs the standard library.

    Loading the two leaf modules by path keeps the adapter runnable under any
    Python 3 with nothing installed, which is what an adapter should be.
    """
    path = _IRINBENCH / f"{module}.py"
    if not path.exists():
        sys.exit(
            f"cannot find {path}. Run this from an IRIN checkout, or copy "
            f"irinbench/{module}.py next to this script."
        )
    spec = importlib.util.spec_from_file_location(f"_irin_{module}", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


_extract = _load("extract")
_transport = _load("transport")

extract_source = _extract.extract_source
error_message = _transport.error_message
was_never_asked = _transport.was_never_asked
NEVER_ASKED = _transport.NEVER_ASKED

#: Some providers reject the default urllib agent string at the edge.
USER_AGENT = "irinbench/1.0 (+https://github.com/nevodesigns/irin)"

INSTRUCTION = """Write CAD source using the build123d Python library.

Output ONLY Python source code. No prose, no explanation, no markdown fences.

The file must define a function gen_step() that takes no arguments and returns
the finished build123d part object. Work in millimetres.

Requirement:
"""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set")
    return value


def _api_key() -> str:
    """Read the key from a file by preference, so it stays out of the process list."""
    key_file = os.environ.get("IRIN_API_KEY_FILE", "").strip()
    if key_file:
        return Path(key_file).expanduser().read_text(encoding="utf-8").strip()
    return _require("IRIN_API_KEY")


def _post(base: str, key: str, body: dict) -> dict | None:
    """Return the decoded reply, or ``None`` if the request never got through."""
    request = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Without this urllib announces itself as Python-urllib/3.x, which
            # more than one provider's edge blocks outright with a 403 before
            # the request reaches the API. curl works against the same endpoint
            # with the same key, which makes it look like an auth problem and
            # sends you to check the key. It is not the key.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    timeout = float(os.environ.get("IRIN_API_TIMEOUT", "240"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A refusal still has a body, and the body says whether it was about
        # reachability or about the request itself. Read it before deciding.
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            print(f"HTTP {exc.code}", file=sys.stderr)
            return None
    except Exception as exc:  # noqa: BLE001 - a socket failure is never the model's answer
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    base = _require("IRIN_API_BASE")
    model = _require("IRIN_API_MODEL")
    key = _api_key()
    prompt = sys.stdin.read()

    body: dict = {
        "model": model,
        "max_tokens": int(os.environ.get("IRIN_API_MAX_TOKENS", "4000")),
        "messages": [{"role": "user", "content": INSTRUCTION + prompt}],
    }
    # Reasoning models spend the budget thinking and return empty content when
    # the effort is high and the cap is modest. Ignored by models without it.
    effort = os.environ.get("IRIN_REASONING_EFFORT", "").strip()
    if effort:
        body["reasoning_effort"] = effort

    # Pacing is the caller's business, but some free tiers refuse a burst
    # outright, and a refused request costs more time than a paced one.
    time.sleep(float(os.environ.get("IRIN_API_DELAY", "0")))

    payload = _post(base, key, body)
    if payload is None:
        return NEVER_ASKED

    message = error_message(payload)
    if message is not None:
        print(message[:200], file=sys.stderr)
        if was_never_asked(message):
            return NEVER_ASKED
        # A refusal about the request itself. The model was reached and
        # declined, which is an answer, and an empty one.
        return 0

    choices = payload.get("choices") or []
    if not choices:
        return 0
    content = (choices[0].get("message") or {}).get("content") or ""

    source = extract_source(content)
    if source:
        sys.stdout.write(source)
    # No source in the reply is the model's result, not a transport failure.
    # Writing nothing scores it as a missing artifact, which is what it is.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
