import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GATE, commit_and_switch, commit_file, fake_gh, git_repo, job, mistakes


class MergeGateTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        self.cwd = self.repo.name

    def gate(self, command, ci_exit=0, ci_out="", ci_err="", head=None, head_exit=0, **extra_env):
        fake_gh(self.bin.name, ci_exit, ci_out, ci_err, head=head, head_exit=head_exit)
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"], **extra_env)
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                   "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, GATE], input=json.dumps(payload), capture_output=True,
                           text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def complete(self, door=True):
        job(self.cwd, "start", "작업")
        job(self.cwd, "red", "test -f done.txt")
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        job(self.cwd, "green")
        shot = os.path.join(self.cwd, "s.png")
        open(shot, "w").close()
        job(self.cwd, "evidence", "기준", shot)
        job(self.cwd, "tried", "써 봄", shot)
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")
        if door:
            job(self.cwd, "door", "two-way", "스크립트만 바뀐다")

    def head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                              text=True).stdout.strip()

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
        self.assertIn("`job.py check`", out["permissionDecisionReason"])  # 빠진 것은 show 가 아니라 check 가 낸다

    def test_다_채우고_CI_가_통과하면_말하지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("git push origin x && gh pr merge 3 --merge"))

    def test_사소한_지적을_모아_고친_커밋의_리뷰도_병합_조건의_리뷰로_친다(self):
        commit_and_switch(self.cwd, "feat/x")  # 앞 리뷰를 남길 커밋이 있어야 한다
        self.complete()
        commit_file(self.cwd, "nit.txt", "사소한 수정\n")
        shot = os.path.join(self.cwd, "s.png")
        job(self.cwd, "green")
        job(self.cwd, "evidence", "기준", shot)
        job(self.cwd, "tried", "써 봄", shot)
        out = self.gate("gh pr merge 3 --squash")
        self.assertIn("리뷰: 마지막 커밋", out["permissionDecisionReason"])
        self.assertEqual(job(self.cwd, "review", "0", "사소한 지적 둘을 고침", "--minor").returncode, 0)
        self.assertIsNone(self.gate("gh pr merge 3 --squash"))

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

    def paths_evidence(self):
        """경로를 적은 증거와 써 보기를 남긴 뒤 다른 파일을 고친 커밋을 더하고, green 과 리뷰만 다시 한다."""
        commit_and_switch(self.cwd, "feat/x")
        commit_file(self.cwd, "src/a.py", "a = 1\n")
        commit_file(self.cwd, "done.txt", "")
        job(self.cwd, "start", "작업")
        job(self.cwd, "red", "test -f missing.txt")
        commit_file(self.cwd, "missing.txt", "")
        job(self.cwd, "green")
        shot = os.path.join(self.bin.name, "s.png")
        open(shot, "w").close()
        job(self.cwd, "log", "기준", "echo 실제=1", "--paths", "src/a.py")
        job(self.cwd, "tried", "써 봄", shot, "--paths", "src/a.py")
        job(self.cwd, "door", "two-way", "스크립트만 바뀐다")

    def again(self):
        job(self.cwd, "green")
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")

    def test_증거가_기대는_경로가_안_바뀐_커밋은_다시_찍지_않아도_병합한다(self):
        self.paths_evidence()
        commit_file(self.cwd, "README.md", "글\n")
        self.again()
        self.assertIsNone(self.gate("gh pr merge 3 --squash", head=self.head()))

    def test_증거가_기대는_경로가_바뀐_커밋은_막는다(self):
        self.paths_evidence()
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        self.again()
        out = self.gate("gh pr merge 3 --squash", head=self.head())
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("낡은 증거", out["permissionDecisionReason"])
        self.assertIn("직접 써 보기: 낡은 기록", out["permissionDecisionReason"])

    def test_PR_최신_커밋이_검증한_로컬_HEAD_와_다르면_막는다(self):
        commit_and_switch(self.cwd, "feat/x")
        self.complete()
        out = self.gate("gh pr merge 3 --squash", head="0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("0123456", out["permissionDecisionReason"])
        self.assertIn(self.head()[:7], out["permissionDecisionReason"])

    def test_PR_최신_커밋이_로컬_HEAD_와_같으면_막지_않는다(self):
        commit_and_switch(self.cwd, "feat/x")
        self.complete()
        self.assertIsNone(self.gate("gh pr merge 3 --squash", head=self.head()))

    def test_gh_pr_view_가_오류로_끝나면_커밋_대조를_하지_않는다(self):
        commit_and_switch(self.cwd, "feat/x")
        self.complete()
        self.assertIsNone(self.gate("gh pr merge 3 --squash"))  # PR 을 못 찾음
        self.assertIsNone(self.gate("gh pr merge 3 --squash", head="0123456", head_exit=1))
        self.assertIsNone(self.gate("gh pr merge 3 --squash", head=""))  # 읽은 값이 비었다

    def test_되돌릴_수_있는가_기록만_없어도_막는다(self):
        self.complete(door=False)
        out = self.gate("gh pr merge 3 --squash")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("되돌릴 수 있는가", out["permissionDecisionReason"])

    def test_한쪽_문이면_막는다(self):
        self.complete()
        job(self.cwd, "door", "one-way", "배포가 함께 나간다")
        out = self.gate("gh pr merge 3 --squash")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("한쪽 문", out["permissionDecisionReason"])

    def test_막으면_실수_기록에_남긴다(self):
        job(self.cwd, "start", "작업")
        job(self.cwd, "pr", "https://github.com/o/r/pull/3")
        before = len(mistakes())
        self.assertEqual(self.gate("gh pr merge 3 --squash")["permissionDecision"], "deny")
        rows = mistakes()[before:]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "gate")
        self.assertIn("테스트", rows[0]["what"])
        self.assertEqual(rows[0]["pr"], "https://github.com/o/r/pull/3")

    def test_막지_않으면_실수_기록에_남기지_않는다(self):
        self.complete()
        before = len(mistakes())
        self.assertIsNone(self.gate("gh pr merge 3 --squash"))
        self.assertEqual(len(mistakes()), before)

    def test_실수_기록을_쓸_수_없어도_막는다(self):
        job(self.cwd, "start", "작업")
        blocker = os.path.join(self.cwd, "file")
        open(blocker, "w").close()
        out = self.gate("gh pr merge 3 --squash", FADE_MISTAKES=os.path.join(blocker, "mistakes.jsonl"))
        self.assertEqual(out["permissionDecision"], "deny")

    def test_여러_줄_명령의_뒷줄_병합도_본다(self):
        job(self.cwd, "start", "작업")
        self.assertEqual(self.gate("git push origin x\ngh pr merge 3 --squash")["permissionDecision"], "deny")

    def test_주석_뒤_다음_줄과_낱말_가운데_샵_뒤의_병합도_본다(self):
        job(self.cwd, "start", "작업")
        self.assertEqual(self.gate("git status # 설명\ngh pr merge 3 --squash")["permissionDecision"], "deny")
        self.assertEqual(self.gate("echo a#b; gh pr merge 3 --squash")["permissionDecision"], "deny")
        self.assertIsNone(self.gate("git status # gh pr merge 3 --squash"))

    def test_heredoc_본문의_글자는_명령이_아니다(self):
        job(self.cwd, "start", "작업")
        self.assertIsNone(self.gate("cat > notes.md <<'EOF'\ngh pr merge 3 --squash\nEOF"))
        self.assertIsNone(self.gate('git commit -m "$(cat <<EOF\ngh pr merge 3\nEOF\n)"'))

    def test_입력이_깨져도_막지_않고_평소_흐름으로_넘긴다(self):
        r = subprocess.run([sys.executable, GATE], input="{깨진", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
