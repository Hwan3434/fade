import json
import subprocess
import sys
import unittest

from helpers import PERMISSION, commit_and_switch, git_repo, job


class PermissionGateTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name

    def ask(self, command="git rebase origin/main"):
        payload = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "cwd": self.cwd,
                   "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, PERMISSION], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_사람_없는_job_에서는_승인_창_대신_거부한다(self):
        job(self.cwd, "start", "작업", "--unattended")
        out = self.ask()
        self.assertEqual(out["hookEventName"], "PermissionRequest")
        self.assertEqual(out["decision"]["behavior"], "deny")
        self.assertIn("git rebase origin/main", out["decision"]["message"])
        self.assertIn("job.py stop", out["decision"]["message"])

    def test_사람이_있는_job_에서는_말하지_않는다(self):
        job(self.cwd, "start", "작업")
        self.assertIsNone(self.ask())

    def test_job_기록이_없으면_말하지_않는다(self):
        self.assertIsNone(self.ask())

    def test_다른_브랜치에서는_말하지_않는다(self):
        job(self.cwd, "start", "작업", "--unattended")
        commit_and_switch(self.cwd, "other")
        self.assertIsNone(self.ask())

    def test_입력이_깨져도_막지_않는다(self):
        r = subprocess.run([sys.executable, PERMISSION], input="{깨진", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
