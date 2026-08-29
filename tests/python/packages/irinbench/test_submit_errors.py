"""A command that never ran is not an agent that answered with nothing.

`submit` runs the agent command with its working directory set to the
submission folder, so a relative --command path resolves against that rather
than against wherever the operator typed it. The shell exits 127, nothing
reaches stdout, and every task recorded "agent produced no output" in 0.0
seconds.

That is a real and expected outcome for a model, so the run reads as a bad
model rather than a command that never started. Discarding stderr was what made
it hard to see: the shell had said exactly what was wrong, twenty-eight times.
"""

from __future__ import annotations

import unittest

from irinbench.submit import _command_failure


class CommandFailureTests(unittest.TestCase):
    def test_a_missing_command_says_so_and_says_why(self):
        message = _command_failure(127, "/bin/sh: 1: adapter.py: not found")
        self.assertIn("could not be run", message)
        self.assertIn("not found", message)
        # The cause is the working directory, so the fix has to be named.
        self.assertIn("absolute path", message)

    def test_a_missing_command_with_no_stderr_still_explains_itself(self):
        message = _command_failure(127, "")
        self.assertIn("could not be run", message)
        self.assertIn("absolute path", message)

    def test_a_crashing_command_reports_its_own_last_words(self):
        message = _command_failure(1, "Traceback...\nModuleNotFoundError: no irinspec")
        self.assertIn("exited 1", message)
        self.assertIn("ModuleNotFoundError", message)

    def test_a_clean_exit_is_not_an_error(self):
        # The agent ran and chose to answer with nothing. That is its result.
        self.assertEqual(_command_failure(0, ""), "")

    def test_a_clean_exit_with_chatter_on_stderr_is_still_not_an_error(self):
        # Adapters log progress to stderr. Only the exit code decides.
        self.assertEqual(_command_failure(0, "asking gemini-3.6-flash"), "")

    def test_the_never_asked_code_is_left_for_the_caller_to_classify(self):
        # 75 means the model was never reached, which submit reports separately
        # under NEVER ASKED. It must not be relabelled as a crash here.
        self.assertEqual(_command_failure(75, "Rate limit exceeded"), "")


if __name__ == "__main__":
    unittest.main()
