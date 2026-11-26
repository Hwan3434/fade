import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GATE, commit_and_switch, fake_gh, git_repo, job


class MergeGateTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        self.cwd = self.repo.name

    def gate(self, command, ci_exit=0, ci_out="", ci_err=""):
        fake_gh(self.bin.name, ci_exit, ci_out, ci_err)
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"])
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                   "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, GATE], input=json.dumps(payload), capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def complete(self):
        job(self.cwd, "start", "작업")
        job(self.cwd, "red", "test -f done.txt")
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        job(self.cwd, "green")
        shot = os.path.join(self.cwd, "s.png")
        open(shot, "w").close()
        job(self.cwd, "evidence", "기준", shot)
        job(self.cwd, "tried", "써 봄", shot)

    def test_병합이_아닌_명령에는_말하지_않는다(self):
        self.assertIsNone(self.gate("gh pr view 3"))
        self.assertIsNone(self.gate("echo gh pr merge"))  # 인용된 글자는 명령이 아니다

    def test_job_기록이_없는_곳에서는_말하지_않는다(self):
        self.assertIsNone(self.gate("gh pr merge 3 --squash"))

    def test_기록이_모자라면_막고_빠진_것을_알린다(self):
        job(self.cwd, "start", "작업")
        out = self.gate("gh pr merge 3 --squash")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("테스트", out["permissionDecisionReason"])

    def test_다_채우고_CI_가_통과하면_말하지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("git push origin x && gh pr merge 3 --merge"))

    def test_CI_가_돌고_있거나_실패하면_막는다(self):
        self.complete()
        self.assertEqual(self.gate("gh pr merge 3", ci_exit=8)["permissionDecision"], "deny")
        self.assertEqual(self.gate("gh pr merge 3", ci_exit=1, ci_out="test\tfail")["permissionDecision"], "deny")

    def test_CI_가_없는_레포는_막지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("gh pr merge 3", ci_exit=1, ci_err="no checks reported on the 'x' branch"))

    def test_gh_가_오류로_끝나면_CI_실패로_치지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("gh pr merge 3", ci_exit=1, ci_err="no git remotes found"))

    def test_PR_까지만인_작업은_막는다(self):
        job(self.cwd, "start", "작업", "--pr-only")
        out = self.gate("gh pr merge 3 --squash")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("PR 까지만", out["permissionDecisionReason"])

    def test_다른_브랜치에서는_말하지_않는다(self):
        job(self.cwd, "start", "작업")
        commit_and_switch(self.cwd, "other")
        self.assertIsNone(self.gate("gh pr merge 3 --squash"))

    def test_시작한_뒤_브랜치를_바꿔도_그_뒤의_기록을_따라간다(self):
        job(self.cwd, "start", "작업")
        commit_and_switch(self.cwd, "feat/renamed")
        job(self.cwd, "no-test", "장치 없음")
        out = self.gate("gh pr merge 3 --squash")
        self.assertEqual(out["permissionDecision"], "deny")

    def test_병합이_기록된_작업은_더_막지_않는다(self):
        job(self.cwd, "start", "작업")
        job(self.cwd, "merged", "abc1234")
        self.assertIsNone(self.gate("gh pr merge 9 --squash"))

    def test_값이_붙는_옵션의_값을_PR_번호로_읽지_않는다(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("merge_gate", GATE)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        pr_target = gate.pr_target
        self.assertEqual(pr_target(["--squash", "--subject", "제목", "3"]), (["3"], []))
        self.assertEqual(pr_target(["-R", "o/r", "--body", "본문", "12"]), (["12"], ["-R", "o/r"]))
        self.assertEqual(pr_target(["--squash"]), ([], []))

    def test_입력이_깨져도_막지_않고_평소_흐름으로_넘긴다(self):
        r = subprocess.run([sys.executable, GATE], input="{깨진", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
