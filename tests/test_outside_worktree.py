"""워커의 워크트리가 레포 밖(환경이 정한 다른 폴더)에 있어도 훅이 그 기록을 찾는다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GATE, PERMISSION, commit_file, git_repo, job
from test_gaps import fake_gh


class OutsideWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.main = os.path.realpath(self.repo.name)
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=self.main, check=True)
        commit_file(self.main, "a.txt", "a\n", "처음")
        self.other = tempfile.TemporaryDirectory()  # 레포 밖, 환경이 워크트리를 두는 다른 폴더
        self.addCleanup(self.other.cleanup)
        self.wt = os.path.join(os.path.realpath(self.other.name), "workspaces", "repo", "x")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "feat/x", self.wt], cwd=self.main, check=True)
        self.addCleanup(subprocess.run, ["git", "worktree", "remove", "--force", self.wt], cwd=self.main)
        job(self.wt, "start", "작업", "--unattended")
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)

    def run_hook(self, script, payload):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.wt, capture_output=True, text=True).stdout.strip()
        fake_gh(self.bin.name, "feat/x", head=head)
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"])
        r = subprocess.run([sys.executable, script], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_메인_체크아웃의_gh_pr_merge_가_레포_밖_워크트리의_기록을_본다(self):
        out = self.run_hook(GATE, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.main,
                                   "tool_input": {"command": "gh pr merge 3 --squash"}})
        self.assertEqual(out["permissionDecision"], "deny")

    def test_base_에서의_git_merge_가_레포_밖_워크트리의_기록을_본다(self):
        out = self.run_hook(GATE, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.main,
                                   "tool_input": {"command": "git merge feat/x"}})
        self.assertEqual(out["permissionDecision"], "deny")

    def test_승인_창_훅이_레포_밖_워크트리를_가리키는_명령의_기록을_본다(self):
        out = self.run_hook(PERMISSION, {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "cwd": self.main,
                                         "tool_input": {"command": "git -C %s push" % self.wt}})
        self.assertEqual(out["decision"]["behavior"], "deny")


if __name__ == "__main__":
    unittest.main()
