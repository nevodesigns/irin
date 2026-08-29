"""Decoding a chat reply into source.

Every case here is one this repository's own adapters got wrong against a real
model, and each one published a number that was too low without looking wrong.
"""

from __future__ import annotations

import unittest

from irinbench.extract import extract_source

CODE = (
    "from build123d import Align, Box, BuildPart\n"
    "\n"
    "def gen_step():\n"
    "    with BuildPart() as part:\n"
    "        Box(40.0, 25.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
    "    return part.part"
)


class FencedTests(unittest.TestCase):
    def test_a_properly_fenced_block(self):
        self.assertEqual(extract_source(f"Sure.\n```python\n{CODE}\n```\nHope that helps."), CODE)

    def test_a_fence_with_no_language_tag(self):
        self.assertEqual(extract_source(f"```\n{CODE}\n```"), CODE)

    def test_bare_source_is_returned_unchanged(self):
        self.assertEqual(extract_source(CODE), CODE)

    def test_the_first_block_wins_when_there_are_several(self):
        reply = f"```python\n{CODE}\n```\nand an alternative:\n```python\nprint(1)\n```"
        self.assertEqual(extract_source(reply), CODE)


class UnbalancedFenceTests(unittest.TestCase):
    """A reply cut off at the token limit, or one missing its opening fence.

    The extractor required a matched pair, so it fell through and wrote the
    stray fence marker into the artifact. That turns valid source into a
    SyntaxError, and a SyntaxError used to poison every other file beside it.
    """

    def test_an_opening_fence_whose_close_was_truncated_away(self):
        # Real: nemotron, radial-engine-cylinder. Output stopped at the budget.
        self.assertEqual(extract_source(f"```python\n{CODE}"), CODE)

    def test_a_closing_fence_with_no_opening_one(self):
        # Real: nemotron, mounting-plate. The file ended with a bare ```.
        self.assertEqual(extract_source(f"{CODE}\n```"), CODE)

    def test_an_echoed_prompt_then_a_fence_then_code(self):
        # Real: the local llama.cpp adapter, eight files. The runner echoed the
        # instruction despite --no-display-prompt, and the closing fence never
        # arrived, so prompt and code landed in the artifact together.
        reply = (
            "Output only Python code. Define a function gen_step() that takes\n"
            "no arguments. Work in millimetres.\n"
            "\n"
            "Requirement:\n"
            "An L-bracket from 8 mm plate.\n"
            f"```python\n{CODE}"
        )
        self.assertEqual(extract_source(reply), CODE)

    def test_neither_side_recognisable_still_returns_something(self):
        # An odd reply is content, and must reach the scorer to be scored.
        out = extract_source("some words\n```\nmore words that go on for longer")
        self.assertIn("more words", out)


class LeadingReasoningTests(unittest.TestCase):
    """Reasoning emitted before the answer is framing, not the answer."""

    def test_prose_before_the_code_is_dropped(self):
        # Real: nemotron, pillow-block. Fifty-four lines of deliberation, then a
        # complete generator. The whole reply was written out and scored zero.
        reply = (
            "We need to write build123d code for a pillow block. The base is\n"
            "90 x 30 mm and the bore axis sits 30 mm above it. Let's assume the\n"
            "holes are 70 mm apart (so x = 10 and x = 80).\n"
            "\n"
            f"{CODE}"
        )
        self.assertEqual(extract_source(reply), CODE)

    def test_reasoning_with_no_code_at_all_stays_a_failure(self):
        # Real: nemotron, clevis-bracket. It never wrote code, and that is the
        # model's result. Recovering something here would be inventing an answer.
        prose = (
            "We need to interpret the geometry. Usually a clevis bracket is a U\n"
            "shape with two ears. Actually, wait. Let's reconsider the base.\n"
        )
        self.assertEqual(extract_source(prose), prose.strip())

    def test_the_word_import_inside_prose_does_not_trigger_a_cut(self):
        # A loose test would find "import" in a sentence and return an essay
        # starting mid-paragraph.
        prose = (
            "It is important to note that build123d uses millimetres.\n"
            "from there, the part is straightforward to describe.\n"
        )
        self.assertEqual(extract_source(prose), prose.strip())

    def test_an_import_without_gen_step_is_not_treated_as_the_answer(self):
        # Both signals are required. One alone is too weak.
        reply = "We could import build123d as bd and go from there, but I am not sure."
        self.assertEqual(extract_source(reply), reply)


class EmptyTests(unittest.TestCase):
    def test_nothing_in_nothing_out(self):
        self.assertEqual(extract_source(""), "")
        self.assertEqual(extract_source("   \n\n  "), "")



class DeclaredReasoningTests(unittest.TestCase):
    """A model that writes <think> has told you where its answer is not.

    This must run before anything else looks for code. A model reasoning about
    build123d writes build123d inside the block: it drafts an import,
    reconsiders, and writes a different one below. Searching the whole reply for
    the first column-zero import finds the draft it threw away.
    """

    def test_the_answer_after_a_think_block_wins_over_the_draft_inside_it(self):
        reply = (
            "<think>\n"
            "I should probably write:\n"
            "from build123d import Cylinder\n"
            "def gen_step(): return Cylinder(5, 10)\n"
            "No, wait. The task wants a box.\n"
            "</think>\n"
            "\n"
            f"{CODE}"
        )
        out = extract_source(reply)
        self.assertEqual(out, CODE)
        self.assertNotIn("Cylinder", out)
        self.assertNotIn("</think>", out)

    def test_a_fenced_answer_after_a_think_block(self):
        self.assertEqual(
            extract_source(f"<think>\nsome deliberation\n</think>\n```python\n{CODE}\n```"),
            CODE,
        )

    def test_the_last_close_wins_when_there_are_several(self):
        reply = f"<think>a</think>\nhmm\n<think>b</think>\n{CODE}"
        self.assertEqual(extract_source(reply), CODE)

    def test_an_unclosed_block_means_it_never_stopped_thinking(self):
        # Cut off at the budget mid-thought. There is no answer after it, and
        # handing back half a thought would score deliberation as an attempt.
        self.assertEqual(
            extract_source("<think>\nThe base is 40 mm. Let me reconsider the ears"),
            "",
        )

    def test_the_alternative_spellings(self):
        for tag in ("thinking", "reasoning"):
            with self.subTest(tag=tag):
                self.assertEqual(extract_source(f"<{tag}>x</{tag}>\n{CODE}"), CODE)

    def test_a_reply_with_no_tags_is_untouched(self):
        self.assertEqual(extract_source(CODE), CODE)


if __name__ == "__main__":
    unittest.main()
