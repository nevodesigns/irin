"""One error type, carrying enough context to fix the spec without guessing.

A spec is usually hand-written or generated, and the person reading the failure
is looking at a JSON file, not a stack trace. So every message names the path it
failed at (``assertions[2].tolerance.plus``) and says what was expected, rather
than surfacing a raw ``KeyError`` from somewhere inside the parser.
"""

from __future__ import annotations


class SpecError(ValueError):
    """A spec is malformed, or describes something that cannot be checked.

    Deliberately a ``ValueError`` subclass: a bad spec is bad input, and callers
    that already handle invalid input do not need a new except clause to keep
    working.
    """
