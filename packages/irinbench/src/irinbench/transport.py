"""Tell a question that was never asked from an answer that was empty.

This is the distinction the whole partial-run machinery rests on, and it is
easy to get backwards. A model that returns nothing has answered, and scores as
a failure. A model that could not be reached has not answered, and scoring it as
a failure publishes somebody's rate limiter as a modelling weakness.

Providers make that hard to read. The same HTTP 200 carries a real reply, a
quota refusal, an expired key and a billing wall, and they disagree about where
in the body the error goes: OpenAI nests it under ``error``, others put
``message`` at the top level. A Cerebras payment wall was once scored as a model
answering with nothing, because the adapter looked only for the nested shape.

Access failures belong on the never-asked side alongside rate limits. A rejected
key says nothing whatsoever about the model, and neither does an unpaid invoice.
"""

from __future__ import annotations

from typing import Any

__all__ = ["NEVER_ASKED", "as_payload", "error_message", "was_never_asked"]

#: Exit status meaning "the question never reached the model". `submit` lists
#: these under NEVER ASKED rather than recording an empty artifact. 75 is
#: EX_TEMPFAIL, which is conventional for a retryable failure.
NEVER_ASKED = 75

#: Substrings that mean the request did not get through. Deliberately about
#: reachability and entitlement, never about the content of a reply.
_NEVER_ASKED_MARKERS = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    # Google's wording for a quota, and the gRPC status behind it. Neither
    # contains the word "quota", so a marker list written from OpenAI's
    # vocabulary alone reads a rate limit as a model that answered.
    "resource exhausted",
    "resource_exhausted",
    "exhausted",
    "overloaded",
    "unavailable",
    "capacity",
    "timeout",
    "timed out",
    "payment",
    "billing",
    "insufficient",
    "credit",
    "invalid api key",
    "unauthorized",
    "forbidden",
    "authentication",
    "permission",
)



def as_payload(decoded: Any) -> dict[str, Any]:
    """Normalise a decoded JSON body to the object the rest of this expects.

    Google returns a top-level JSON *array* for errors, one element holding the
    error object, while its successful replies are the ordinary object every
    other provider sends. An adapter written against the documented shape
    therefore works perfectly until the first rate limit, then crashes on a list
    where it expected a dict.

    Anything that is not an object and not a one-element array of one is
    reported as an empty payload, which reads downstream as a reply with no
    choices and no error: nothing usable arrived.
    """
    if isinstance(decoded, dict):
        return decoded
    if isinstance(decoded, list):
        for item in decoded:
            if isinstance(item, dict):
                return item
    return {}


def error_message(payload: dict[str, Any]) -> str | None:
    """Return the error in ``payload``, whichever envelope the provider used.

    ``None`` means the payload carries a reply rather than an error. A payload
    holding both an error and choices is treated as a reply, because the model
    did produce something and a warning alongside it is not a failure to answer.
    """
    if payload.get("choices"):
        return None

    error = payload.get("error")
    if error is None and payload.get("message"):
        # Top-level {"message": ..., "type": ...}. A billing wall arrives in
        # this shape and used to read as a model that answered with nothing.
        error = payload
    if error is None:
        return None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def was_never_asked(message: str) -> bool:
    """Does ``message`` mean the request never reached the model?"""
    lowered = message.lower()
    return any(marker in lowered for marker in _NEVER_ASKED_MARKERS)
