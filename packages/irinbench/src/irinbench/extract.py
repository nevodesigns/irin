"""Recover CAD source from what a chat model actually returns.

Every adopter of this benchmark has to write this step, because a chat model
does not return a file. It returns a reply, and the source is somewhere inside
it. That decoding is the adapter's job, and it is worth being careful about:
three separate bugs in this repository's own adapters each published a number
that was too low, and none of them looked wrong.

The distinction this module draws, and it is the whole design:

**Framing is the adapter's problem. Content is the model's.** A markdown fence
is framing. A prompt echoed back by a local runner is framing. Reasoning the
model emitted before its answer is framing. None of those are the model's
attempt at the requirement, and writing them into the artifact scores the
adapter's transport rather than the model's engineering.

A reply with no source in it at all is content, and stays a failure. A model
that spent its whole budget thinking and never wrote code has not answered, and
must score as not having answered. The line is drawn at whether source is
present, never at whether it is any good: nothing here repairs, completes or
tidies code, because that would measure the repair.
"""

from __future__ import annotations

import ast
import re

__all__ = ["extract_source"]

_FENCE = re.compile(r"^[ \t]*```[^\n]*$", re.MULTILINE)
_PAIRED = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
#: A line that can only be the start of Python source, at column zero.
_CODE_START = re.compile(r"^(?:import[ \t]|from[ \t]+\S+[ \t]+import\b)", re.MULTILINE)
#: Reasoning channels a model marks off explicitly. Everything a model puts
#: inside one of these is by its own declaration not the answer.
_THINK_CLOSE = re.compile(r"</(?:think|thinking|reasoning)>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<(?:think|thinking|reasoning)>", re.IGNORECASE)


def extract_source(raw: str) -> str:
    """Return the source in ``raw``, or ``""`` if it holds none.

    Handles, in order of how often they actually occur:

    1. A properly fenced block. The common case.
    2. Exactly one fence, because the reply was cut off at the token limit
       before the closing one, or because the opening one was never emitted.
       An unbalanced fence used to be left in the file, which turned otherwise
       valid source into a ``SyntaxError``.
    3. No fence, with reasoning ahead of the code. One model wrote fifty-four
       lines of deliberation and then a correct generator; the whole reply was
       written to disk and the task scored zero.
    """
    text = _drop_declared_reasoning(raw.strip())
    if not text:
        return ""

    paired = _PAIRED.search(text)
    if paired:
        return paired.group(1).strip()

    fences = list(_FENCE.finditer(text))
    if len(fences) == 1:
        fence = fences[0]
        before = text[: fence.start()].strip()
        after = text[fence.end() :].strip()
        # Whichever side holds source. A fence on line one means the closing one
        # was truncated away, so the code is after it; a fence at the end means
        # the opening one was lost or prose follows, so the code is before it.
        if _looks_like_source(after) and not _looks_like_source(before):
            return after
        if _looks_like_source(before):
            return before
        # Neither side is recognisable. Return the longer side rather than
        # nothing, so a genuinely odd reply is still scored on its content.
        return after if len(after) > len(before) else before

    return _drop_trailing_prose(_strip_leading_prose(text))


def _drop_declared_reasoning(text: str) -> str:
    """Remove a reasoning channel the model marked off itself.

    A model that writes ``<think>`` has told you where its answer is not. This
    has to run before anything else looks for code, because a model reasoning
    about build123d writes build123d inside the block: it drafts an import,
    reconsiders, and writes a different one below. Searching the whole reply for
    the first import at column zero finds the draft it discarded, and returns
    that plus the rest of the deliberation.

    An unclosed tag means the reply was cut off while still thinking. There is
    no answer after it, so the whole thing is reasoning and the caller should
    see it as such rather than be handed half a thought.
    """
    closes = list(_THINK_CLOSE.finditer(text))
    if closes:
        # The last close, not the first: nested or repeated blocks both end
        # before the answer starts.
        return text[closes[-1].end() :].strip()
    if _THINK_OPEN.search(text):
        return ""
    return text



def _parses(text: str) -> bool:
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return True



#: A line that opens a block of Python. Matched against the first non-empty line
#: of what would be discarded, never against the body: deliberation about code
#: quotes code, so "the gussets at x=0 and x=80" contains an assignment and a
#: call and is still a sentence. Where a passage *starts* separates the two
#: reliably, because prose starts with words and code starts with statements.
_CODE_OPENER = re.compile(
    r"^[ \t]*(?:def |class |import |from |@\w|return\b|with |for |while |if |try:|"
    r"[A-Za-z_][\w.\[\]]*\s*=[^=]|[A-Za-z_][\w.]*\()"
)


def _opens_like_code(text: str) -> bool:
    """Does this passage begin as code rather than as a sentence?"""
    for line in text.splitlines():
        if not line.strip():
            continue
        return bool(_CODE_OPENER.match(line))
    return False


def _drop_trailing_prose(text: str) -> str:
    """Drop commentary a model appended after it had finished the code.

    A model wrote a complete generator, then kept going: "One issue: the gussets
    we created as extruded triangles...". Thirteen kilobytes, of which the first
    fifty lines were the answer and the rest was the model talking to itself
    about the answer. There is no fence to cut on and the prose sits *after* the
    code, so neither the fence rules nor the leading-prose rule touch it.

    The cut has to be conservative, because the obvious version of it repairs
    code. Truncating any unparseable reply at its longest valid prefix would
    turn a model's genuine syntax error into a shorter, working file and score
    the truncation rather than the model. So two conditions both have to hold:
    the prefix must parse and still define gen_step, and what is being removed
    must not look like source. Prose is framing. Code, however broken, is the
    model's answer and stays.
    """
    if _parses(text) or "def gen_step" not in text:
        return text

    lines = text.splitlines()
    for cut in range(len(lines) - 1, 0, -1):
        prefix = "\n".join(lines[:cut])
        if "def gen_step" not in prefix:
            # Cut back past the answer itself. Nothing here to recover.
            return text
        if not _parses(prefix):
            continue
        # The longest parsing prefix. Whatever follows it decides: prose is
        # framing to drop, source is the model's own broken code to keep.
        tail = "\n".join(lines[cut:])
        if "def gen_step" in tail:
            # A second attempt at the answer, not commentary about the first.
            # Returning the earlier one because the later one does not compile
            # would hand back work the model itself superseded, which is the
            # same repair this rule exists to avoid.
            return text
        if _opens_like_code(tail):
            return text
        return prefix.rstrip()
    return text


def _looks_like_source(text: str) -> bool:
    """Is this Python, rather than prose about Python?

    Deliberately strict. A loose test would find the word "import" in a
    paragraph of reasoning and hand back an essay.
    """
    return bool(_CODE_START.search(text)) or "def gen_step" in text


def _strip_leading_prose(text: str) -> str:
    """Drop reasoning that precedes the source, and nothing else.

    Two independent signals are required: a line beginning at column zero with
    an import, and a ``gen_step`` definition somewhere after it. Prose does not
    begin a line with ``import build123d`` and then go on to define the exact
    function the task asked for.

    Without both, the text is returned untouched. A reply that is only
    deliberation must reach the scorer as only deliberation.
    """
    if "def gen_step" not in text:
        return text

    match = _CODE_START.search(text)
    if match is None:
        return text
    if "def gen_step" not in text[match.start() :]:
        return text
    return text[match.start() :].strip()
