import json
import os
import unittest

from helpers import PERMISSION, commit_and_switch, git_repo, hook, job, mistakes


class PermissionGateTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name

    def ask(self, command="git rebase origin/main", env=None, crash=False):
        payload = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "cwd": self.cwd,
                   "tool_input": {"command": command}}
        r = hook(PERMISSION, json.dumps(payload), env=env, crash=crash)
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

    def test_거부하면_실수_기록에_남긴다(self):
        job(self.cwd, "start", "작업", "--unattended")
        before = len(mistakes())
        self.ask("git push --force origin feat/x")
        rows = mistakes()[before:]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "permission")
        self.assertIn("git push --force origin feat/x", rows[0]["what"])

    def test_거부하지_않으면_실수_기록에_남기지_않는다(self):
        job(self.cwd, "start", "작업")
        before = len(mistakes())
        self.assertIsNone(self.ask())
        self.assertEqual(len(mistakes()), before)

    def test_실수_기록을_쓸_수_없어도_거부한다(self):
        job(self.cwd, "start", "작업", "--unattended")
        blocker = os.path.join(self.cwd, "file")
        open(blocker, "w").close()
        out = self.ask(env=dict(os.environ, FADE_MISTAKES=os.path.join(blocker, "mistakes.jsonl")), crash=True)
        self.assertEqual(out["decision"]["behavior"], "deny")

    def test_입력이_깨져도_막지_않는다(self):
        r = hook(PERMISSION, "{깨진", crash=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
