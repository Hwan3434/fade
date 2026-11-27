"""병합 조건이 gh pr merge 한 지점에만 걸려 조용히 빠지던 길: base 로 가는 git merge·push, 다른 폴더에서 부른 명령,
테스트 먼저(red 뒤에 구현이 바뀌었나), red 의 실패 출력."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GATE, PERMISSION, ROOT, commit_and_switch, commit_file, git_repo, job

GIT = ["git", "-c", "user.name=fade-test", "-c", "user.email=fade-test@example.invalid"]


def fake_gh(dirpath, branch="feat/x", head=""):
    """`gh pr view` 는 -q 의 칸에 따라 브랜치(headRefName)나 커밋(headRefOid)을, `gh pr checks` 는 검사 줄 없이 답한다."""
    path = os.path.join(dirpath, "gh")
    with open(path, "w") as f:
        f.write("#!/bin/sh\nif [ \"$2\" = view ]; then\n  case \"$*\" in\n"
                "    *headRefName*) printf '%%s\\n' %s ;;\n    *headRefOid*) printf '%%s\\n' %s ;;\n  esac\n  exit 0\nfi\n"
                "exit 0\n" % (repr(branch), repr(head)))
    os.chmod(path, 0o755)
    return dirpath


class Repo(unittest.TestCase):
    """메인 체크아웃(main)과 작업 워크트리(feat/x). 작업 워크트리에서 사람 없는 job 을 시작해 둔다."""

    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.main = os.path.realpath(self.repo.name)
        subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=self.main, check=True)
        commit_file(self.main, "a.txt", "a\n", "처음")
        self.wt = os.path.join(self.main, ".claude", "worktrees", "x")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "feat/x", self.wt], cwd=self.main, check=True)
        self.assertEqual(job(self.wt, "start", "작업", "--unattended").returncode, 0)
        self.bin = tempfile.TemporaryDirectory()
        self.addCleanup(self.bin.cleanup)
        self.outside = tempfile.TemporaryDirectory()  # git 레포가 아닌 폴더
        self.addCleanup(self.outside.cleanup)

    def complete(self):
        job(self.wt, "red", "test -f done.txt")
        commit_file(self.wt, "done.txt", "", "구현")
        job(self.wt, "green")
        shot = os.path.join(job_dir(self.wt), "s.png")
        open(shot, "w").close()
        job(self.wt, "evidence", "기준", shot)
        job(self.wt, "tried", "써 봄", shot)
        job(self.wt, "review", "0", "작은 변경이라 버그 축만")
        job(self.wt, "door", "two-way", "스크립트만")

    def gate(self, command, cwd, branch="feat/x"):
        fake_gh(self.bin.name, branch, head=subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.wt, capture_output=True,
                                                           text=True).stdout.strip())
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"])
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd, "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, GATE], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "", r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def denied(self, command, cwd):
        out = self.gate(command, cwd)
        self.assertIsNotNone(out, command)
        self.assertEqual(out["permissionDecision"], "deny", command)
        return out["permissionDecisionReason"]


def job_dir(cwd):
    return subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True, text=True).stdout.strip()


class GitMergeTest(Repo):
    """PR 없이 base 에 바로 반영하는 갈래도 그 브랜치의 job 기록을 본다."""

    def test_base_에서_작업_브랜치를_합치면_기록을_본다(self):
        self.assertIn("테스트", self.denied("git merge --ff-only feat/x", self.main))

    def test_다른_폴더에서_git_C_로_base_에_합쳐도_본다(self):
        self.denied("git -C %s merge feat/x" % self.main, self.wt)
        self.denied("git -C %s merge feat/x" % self.main, self.outside.name)

    def test_cd_로_base_체크아웃에_들어가_합쳐도_본다(self):
        self.denied("cd %s && git merge --no-ff -m m feat/x" % self.main, self.outside.name)

    def test_원격_추적_브랜치_이름으로_합쳐도_본다(self):
        self.denied("git merge origin/feat/x", self.main)

    def test_작업_브랜치에서_base_를_합치는_것은_막지_않는다(self):
        self.assertIsNone(self.gate("git merge origin/main", self.wt))
        self.assertIsNone(self.gate("git -C %s merge main" % self.wt, self.main))

    def test_기록을_다_채우면_막지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("git merge --ff-only feat/x", self.main))

    def test_job_기록이_없는_브랜치는_보지_않는다(self):
        subprocess.run(["git", "branch", "feat/y"], cwd=self.main, check=True)
        self.assertIsNone(self.gate("git merge feat/y", self.main))

    def test_작업_브랜치를_base_로_push_해도_본다(self):
        for command in ("git push origin feat/x:main", "git push origin HEAD:main", "git push origin HEAD:refs/heads/main"):
            self.denied(command, self.wt)
        self.denied("git -C %s push origin HEAD:main" % self.wt, self.main)
        self.assertIsNone(self.gate("git push origin feat/x", self.wt))
        self.assertIsNone(self.gate("git push -u origin HEAD", self.wt))


class OtherFolderTest(Repo):
    """세션의 현재 폴더가 아니라 명령이 가리키는 폴더와 PR 의 브랜치로 기록을 찾는다."""

    def test_메인_체크아웃에서_gh_pr_merge_해도_PR_브랜치의_워크트리_기록을_본다(self):
        self.denied("gh pr merge 3 --squash", self.main)

    def test_cd_로_워크트리에_들어가_gh_pr_merge_해도_본다(self):
        self.denied("cd %s && gh pr merge 3 --squash" % self.wt, self.outside.name)

    def test_명령이_가리키는_폴더에_기록이_없으면_세션_폴더의_기록을_본다(self):
        for command in ("cd %s && gh pr merge 3 --repo o/r" % self.outside.name, "cd $WT && gh pr merge 3",
                        'cd "$(git rev-parse --show-toplevel)" && gh pr merge 3'):
            self.assertEqual(self.gate(command, self.wt, branch="feat/none")["permissionDecision"], "deny", command)

    def test_PR_브랜치의_워크트리가_없으면_말하지_않는다(self):
        self.assertIsNone(self.gate("gh pr merge 3 --squash", self.main, branch="feat/none"))

    def test_기록을_다_채우면_메인_체크아웃에서도_막지_않는다(self):
        self.complete()
        self.assertIsNone(self.gate("gh pr merge 3 --squash", self.main))

    def ask(self, cwd, tool="Bash", tool_input=None):
        payload = {"hook_event_name": "PermissionRequest", "tool_name": tool, "cwd": cwd, "tool_input": tool_input or {}}
        r = subprocess.run([sys.executable, PERMISSION], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_승인_창_훅도_명령이_가리키는_워크트리의_기록을_본다(self):
        for command in ("git -C %s push" % self.wt, "cd %s && git rebase origin/main" % self.wt):
            out = self.ask(self.main, tool_input={"command": command})
            self.assertEqual(out["decision"]["behavior"], "deny", command)

    def test_승인_창_훅은_파일_도구의_경로로도_찾는다(self):
        out = self.ask(self.main, "Edit", {"file_path": os.path.join(self.wt, "a.txt")})
        self.assertEqual(out["decision"]["behavior"], "deny")

    def test_승인_창_훅은_해석하지_못하는_명령에도_세션_폴더로_거부한다(self):
        out = self.ask(self.wt, tool_input={"command": "echo $'it\\'s'"})
        self.assertEqual(out["decision"]["behavior"], "deny")

    def test_승인_창_훅은_job_과_무관한_명령에_말하지_않는다(self):
        self.assertIsNone(self.ask(self.main, tool_input={"command": "git status"}))
        self.assertIsNone(self.ask(self.outside.name, tool_input={"command": "ls %s" % self.outside.name}))


class TestFirstTest(unittest.TestCase):
    """red 뒤에 red 때 이미 바뀌어 있던 파일 말고 바뀐 것이 없으면 green 을 받지 않는다."""

    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        commit_and_switch(self.cwd, "feat/x")
        commit_file(self.cwd, "impl.py", "x = 0\n")
        job(self.cwd, "start", "작업")

    def write(self, name, text):
        with open(os.path.join(self.cwd, name), "w") as f:
            f.write(text)

    def test_구현이_이미_있는_채_찍은_red_는_green_을_받지_않는다(self):
        self.write("impl.py", "x = 1\n")  # 구현을 먼저 했다
        self.write("t.sh", "grep -q 'x = 1' impl.py && test -f ok\n")
        self.assertEqual(job(self.cwd, "red", "sh t.sh").returncode, 0)
        self.write("t.sh", "grep -q 'x = 1' impl.py\n")  # 테스트만 고쳐 통과시킨다
        subprocess.run(["git", "add", "impl.py", "t.sh"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "x"], cwd=self.cwd, check=True)
        r = job(self.cwd, "green")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("red 뒤에", r.stderr)
        self.assertIn("impl.py", r.stderr)

    def test_아무것도_바꾸지_않고_통과하면_받지_않는다(self):
        self.assertEqual(job(self.cwd, "red", "test -f .git/flag").returncode, 0)
        open(os.path.join(job_dir(self.cwd), "flag"), "w").close()  # 작업 트리 밖이 바뀌어 통과한다(흔들리는 테스트)
        r = job(self.cwd, "green")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("red 뒤에", r.stderr)

    def test_테스트를_먼저_쓰고_구현을_더하면_받는다(self):
        self.write("t.sh", "grep -q 'x = 1' impl.py\n")
        self.assertEqual(job(self.cwd, "red", "sh t.sh").returncode, 0)
        commit_file(self.cwd, "t.sh", "grep -q 'x = 1' impl.py\n", "테스트")
        commit_file(self.cwd, "impl.py", "x = 1\n", "구현")
        r = job(self.cwd, "green")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_테스트를_커밋한_뒤_찍은_red_도_받는다(self):
        commit_file(self.cwd, "t.sh", "grep -q 'x = 1' impl.py\n", "테스트")
        job(self.cwd, "red", "sh t.sh")
        self.write("impl.py", "x = 1\n")  # 커밋 전 구현도 구현이다
        self.assertEqual(job(self.cwd, "green").returncode, 0)


class RedOutputTest(unittest.TestCase):
    """red 는 실패 출력의 끝을 보여 준다. show --full 은 앞서 기록한 실패의 출력도 보여 줘 문법 오류와 진짜 red 가 갈린다."""

    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        commit_and_switch(self.cwd, "feat/x")
        job(self.cwd, "start", "작업")

    def test_red_는_실패_출력의_끝을_찍는다(self):
        r = job(self.cwd, "red", "echo 앞줄; echo AssertionError: 기대 1 실제 0; exit 1")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("red 를 기록했다", lines[0])
        self.assertIn("AssertionError: 기대 1 실제 0", r.stdout)
        self.assertIn("실패 이유", r.stdout)

    def test_show_full_은_앞서_기록한_실패의_출력도_보인다(self):
        # 출력이 명령 글과 다르게 printf 로 찍는다. 기본 출력에도 명령은 나오기 때문이다
        job(self.cwd, "red", "printf 'Syn%sError: invalid syntax\\n' tax; exit 1")
        job(self.cwd, "red", "printf 'Assertion%sError: 구현 없음\\n' ''; exit 1")
        full = job(self.cwd, "show", "--full").stdout
        self.assertIn("SyntaxError: invalid syntax", full)
        self.assertIn("AssertionError: 구현 없음", full)
        self.assertNotIn("SyntaxError", job(self.cwd, "show").stdout)  # 기본 출력은 짧게 둔다


class CommitRuleTextTest(unittest.TestCase):
    """테스트 커밋의 조건을 job 의 커밋 절과 test-first.md 가 같은 말로 한다."""

    RULE = "실패 이유가 아직 구현이 없어서인 것을 읽은 뒤"

    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_두_글이_같은_조건을_말한다(self):
        skill = self.read("skills", "job", "SKILL.md")
        first = self.read("skills", "job", "stages", "test-first.md")
        self.assertIn(self.RULE, skill[skill.index("## 커밋"):])
        self.assertIn(self.RULE, first)
        self.assertNotIn("(`red` 가 기록된 뒤)", skill)


if __name__ == "__main__":
    unittest.main()
