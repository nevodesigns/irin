"""The shipped adapter must run under whatever `python3` a shebang finds.

`submit --command benchmarks/adapters/openai_compatible.py` executes the file,
so the interpreter is whatever `/usr/bin/env python3` resolves to on the
operator's PATH. That is very often not the environment IRIN was installed into.

The first version imported `irinbench.extract`, which runs the package __init__,
which imports the corpus loader, which imports irinspec. Under the repo venv it
worked perfectly and every smoke test passed. Under a bare python3 it died on
ModuleNotFoundError before making a single request, and a full 28-task run
recorded "agent produced no output" for every task in 0.0 seconds.

That failure is quiet in the worst way: `submit` reports it as the agent
answering with nothing, which is a real and expected outcome, so the run looks
like a model that failed rather than an adapter that never started.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
ADAPTER = REPO_ROOT / "benchmarks" / "adapters" / "openai_compatible.py"


class StandaloneTests(unittest.TestCase):
    """It must reach its own argument checks with nothing installed."""

    def _run(self, env_extra: dict[str, str]) -> subprocess.CompletedProcess:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("IRIN_API_", "IRIN_REASONING", "PYTHONPATH"))
        }
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-E", "-s", str(ADAPTER)],
            input="a 40 mm cube",
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def test_it_starts_without_the_irin_packages_on_the_path(self):
        # No IRIN_API_BASE, so it must stop at that check. Reaching the check at
        # all proves the imports resolved.
        result = self._run({})
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("IRIN_API_BASE", result.stderr)

    def test_it_names_the_next_missing_variable_in_turn(self):
        result = self._run({"IRIN_API_BASE": "https://example.invalid/v1"})
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("IRIN_API_MODEL", result.stderr)

    def test_an_unreachable_endpoint_is_never_asked_not_an_empty_answer(self):
        # The distinction the partial-run machinery rests on. A DNS failure must
        # not be recorded as a model that answered with nothing.
        result = self._run(
            {
                "IRIN_API_BASE": "https://not-a-real-host.invalid/v1",
                "IRIN_API_MODEL": "any",
                "IRIN_API_KEY": "x",
            }
        )
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stdout, "")

    def test_it_carries_an_agent_string(self):
        # urllib announces itself as Python-urllib, which more than one provider
        # blocks at the edge with a 403 before the request reaches the API. It
        # reads as an auth failure and sends you to check the key.
        source = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("User-Agent", source)
        self.assertNotIn("Python-urllib", source.split("USER_AGENT")[-1][:200])


if __name__ == "__main__":
    unittest.main()
