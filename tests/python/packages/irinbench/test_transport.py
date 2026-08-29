"""Telling a question that was never asked from an answer that was empty.

Every case here is a real reply shape that a provider returned to this
repository, and getting one of them backwards publishes an account problem as a
modelling weakness.
"""

from __future__ import annotations

import unittest

from irinbench.transport import (
    NEVER_ASKED,
    as_payload,
    error_message,
    was_never_asked,
)


class EnvelopeTests(unittest.TestCase):
    """Providers disagree about where the error goes."""

    def test_the_nested_openai_shape(self):
        payload = {"error": {"message": "Rate limit exceeded", "code": 429}}
        self.assertEqual(error_message(payload), "Rate limit exceeded")

    def test_the_top_level_shape(self):
        # Real: a Cerebras billing wall. The adapter read only the nested shape,
        # found no error, saw no choices, and scored it as an empty answer.
        payload = {"message": "Insufficient credits", "type": "payment_required"}
        self.assertEqual(error_message(payload), "Insufficient credits")

    def test_a_reply_carries_no_error(self):
        payload = {"choices": [{"message": {"content": "code"}}]}
        self.assertIsNone(error_message(payload))

    def test_choices_win_over_a_warning(self):
        # The model produced something. A warning beside it is not a failure
        # to answer, and treating it as one would discard a real reply.
        payload = {
            "error": {"message": "deprecated model"},
            "choices": [{"message": {"content": "code"}}],
        }
        self.assertIsNone(error_message(payload))

    def test_an_empty_payload_is_not_an_error(self):
        self.assertIsNone(error_message({}))

    def test_a_bare_string_error(self):
        self.assertEqual(error_message({"error": "upstream exploded"}), "upstream exploded")


class ClassificationTests(unittest.TestCase):
    """Reachability and entitlement are never-asked. Content is an answer."""

    def test_rate_limits_and_quotas(self):
        for message in (
            "Rate limit exceeded: free-models-per-day",
            "Too Many Requests",
            "You exceeded your current quota",
            "rate_limit_exceeded",
        ):
            with self.subTest(message=message):
                self.assertTrue(was_never_asked(message))

    def test_entitlement_failures_are_never_asked_too(self):
        # A rejected key or an unpaid invoice says nothing about the model, so
        # scoring it as a failed attempt would attribute it to the wrong party.
        for message in (
            "Insufficient credits. Add 10 credits to continue",
            "Invalid API key provided",
            "Unauthorized",
            "payment required",
            "authentication_error",
        ):
            with self.subTest(message=message):
                self.assertTrue(was_never_asked(message))

    def test_capacity_and_transport_failures(self):
        for message in ("The engine is overloaded", "Service unavailable", "request timed out"):
            with self.subTest(message=message):
                self.assertTrue(was_never_asked(message))

    def test_a_complaint_about_the_request_is_an_answer(self):
        # The model was reached. It declined, and that is a result.
        for message in (
            "This model does not support the 'reasoning_effort' parameter",
            "max_tokens is too large for this model",
            "content policy violation",
        ):
            with self.subTest(message=message):
                self.assertFalse(was_never_asked(message))

    def test_the_exit_code_is_the_conventional_one(self):
        # EX_TEMPFAIL. `submit` keys its NEVER ASKED list on exactly this.
        self.assertEqual(NEVER_ASKED, 75)


class ArrayEnvelopeTests(unittest.TestCase):
    """Google returns a top-level JSON array for errors.

    Its successful replies are the ordinary object every other provider sends,
    so an adapter written against the documented shape works perfectly until the
    first rate limit and then crashes on a list where it expected a dict. Nine
    tasks of a real run died this way, each in under five seconds.
    """

    def test_an_error_wrapped_in_an_array(self):
        decoded = [{"error": {"code": 429, "message": "Resource exhausted"}}]
        payload = as_payload(decoded)
        self.assertEqual(error_message(payload), "Resource exhausted")
        self.assertTrue(was_never_asked(error_message(payload)))

    def test_an_ordinary_object_is_untouched(self):
        decoded = {"choices": [{"message": {"content": "code"}}]}
        self.assertIs(as_payload(decoded), decoded)

    def test_an_array_of_replies_takes_the_first(self):
        decoded = [{"choices": [{"message": {"content": "code"}}]}, {"choices": []}]
        self.assertIsNone(error_message(as_payload(decoded)))

    def test_an_empty_array_is_an_empty_payload(self):
        # Nothing usable arrived. Reads downstream as no choices and no error.
        self.assertEqual(as_payload([]), {})

    def test_a_bare_scalar_is_an_empty_payload(self):
        for decoded in ("just a string", 7, None, True):
            with self.subTest(decoded=decoded):
                self.assertEqual(as_payload(decoded), {})

    def test_an_array_of_scalars_is_an_empty_payload(self):
        self.assertEqual(as_payload(["nope", 1]), {})


if __name__ == "__main__":
    unittest.main()
