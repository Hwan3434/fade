"""병합 훅이 폴더를 알 수 없는 조각에서 죽지 않고, 알 수 없으면 세션 폴더의 기록으로 판정한다(2차 작업 A)."""
import json
import os
import subprocess
import sys
import unittest

from helpers import GATE, PERMISSION, commit_and_switch, commit_file, git_repo, job
from test_gaps import Repo, job_dir


class CrashTest(Repo):
    """세션은 기록이 덜 찬 작업 워크트리다. 아래 명령은 모두 막혀야 한다(PR 27 이전 훅은 앞의 셋을 막았다)."""

    def test_cd_뒤에_리다이렉트가_붙어도_죽지_않고_막는다(self):
        self.denied("cd %s >/dev/null 2>&1 && git pull && gh pr merge 3 --squash" % self.wt, self.wt)

    def test_셸_변수_경로의_cd_뒤의_병합은_세션_폴더로_막는다(self):
        self.denied('cd "$WT" && git pull --rebase && gh pr merge 3 --squash', self.wt)

    def test_셸_변수_경로의_git_C_가_같은_줄의_gh_병합을_없애지_않는다(self):
        self.denied('git -C "$MAIN" pull origin main && gh pr merge 3', self.wt)

    def test_cd_뒤_리다이렉트가_붙어도_base_에서의_merge_를_본다(self):
        self.denied("cd %s 2>/dev/null && git merge feat/x" % self.main, self.wt)

    def test_없는_폴더의_git_조각이_훅을_죽이지_않는다(self):
        self.denied("cd /nonexistent/fade-x && git merge feat/x; gh pr merge 3", self.wt)
        self.denied("git -C /nonexistent/fade-x push origin HEAD:main; gh pr merge 3", self.wt)


class RedirectNumberTest(Repo):
    """리다이렉트에 붙은 숫자(2>&1 의 2)만 fd 번호다. 띄어 쓴 숫자(gh pr merge 3 >/dev/null 의 3)는 PR 번호로 남는다."""

    def test_리다이렉트_앞에_띄어_쓴_PR_번호를_지우지_않는다(self):
        # PR 3 을 물을 때만 브랜치를 답하는 gh. 번호 없이 물으면(지금 브랜치 main 의 PR) 아무것도 답하지 않는다
        gh = os.path.join(self.bin.name, "gh")
        with open(gh, "w") as f:
            f.write("#!/bin/sh\ncase \"$*\" in\n  \"pr view 3 \"*headRefName*) echo feat/x ;;\nesac\nexit 0\n")
        os.chmod(gh, 0o755)
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"])
        for command in ("gh pr merge 3 >/dev/null 2>&1", "gh pr merge 3 > log"):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.main,
                       "tool_input": {"command": command}}
            r = subprocess.run([sys.executable, GATE], input=json.dumps(payload), capture_output=True, text=True, env=env)
            # 메인 체크아웃에는 기록이 없어 PR 3 의 브랜치(feat/x)로 찾아야 막힌다
            self.assertTrue(r.stdout.strip(), command)
            self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny", command)


class PrBranchFirstTest(Repo):
    """gh pr merge 는 PR 의 브랜치가 체크아웃된 워크트리의 기록을 먼저 본다. 세션 폴더의 다른 작업 기록이 대신하지 않는다."""

    def test_다른_작업의_워크트리에서_합쳐도_PR_브랜치의_기록을_본다(self):
        self.complete()  # 세션 폴더(feat/x)의 작업은 기록을 다 채웠다
        other = os.path.join(self.main, ".claude", "worktrees", "y")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "feat/y", other], cwd=self.main, check=True)
        job(other, "start", "다른 작업")
        out = self.gate("gh pr merge 4 --squash", self.wt, branch="feat/y")
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")


class KoreanNameTest(unittest.TestCase):
    """git 이 한글 이름을 따옴표로 감싸 내보내도(-z 없이 읽으면) 내용 해시를 잃지 않는다."""

    def test_red_때_바뀌어_있던_한글_이름_파일만_더_고친_정상_흐름은_받는다(self):
        repo = git_repo()
        self.addCleanup(repo.cleanup)
        cwd = repo.name
        commit_and_switch(cwd, "feat/x")
        commit_file(cwd, "계산.py", "x = 0\n")
        job(cwd, "start", "작업")
        with open(os.path.join(cwd, "계산.py"), "w") as f:
            f.write("x = 0\nassert x == 1\n")  # 테스트와 구현이 한 파일이다
        self.assertEqual(job(cwd, "red", "python3 계산.py").returncode, 0)
        with open(os.path.join(cwd, "계산.py"), "w") as f:
            f.write("x = 1\nassert x == 1\n")
        r = job(cwd, "green")
        self.assertEqual(r.returncode, 0, r.stderr)


class WriteNewFolderTest(Repo):
    def test_아직_없는_폴더에_Write_해도_그_워크트리의_기록을_찾는다(self):
        payload = {"hook_event_name": "PermissionRequest", "tool_name": "Write", "cwd": self.main,
                   "tool_input": {"file_path": os.path.join(self.wt, "새", "폴더", "a.py"), "content": "x"}}
        r = subprocess.run([sys.executable, PERMISSION], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")


if __name__ == "__main__":
    unittest.main()
