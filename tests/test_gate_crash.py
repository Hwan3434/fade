"""병합 훅이 폴더를 알 수 없는 조각에서 죽지 않고, 알 수 없으면 세션 폴더의 기록으로 판정한다(2차 작업 A)."""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))

from helpers import GATE, PERMISSION, commit_and_switch, commit_file, git_repo, hook, job
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

    def test_알_수_없는_cd_뒤에도_절대_경로_cd_는_따라간다(self):
        self.denied('cd "$X" && cd %s && git merge feat/x' % self.main, self.wt)

    def test_한_조각의_판정이_실패해도_같은_줄의_다른_병합을_막는다(self):
        import merge_gate
        broken = merge_gate.git_targets
        merge_gate.git_targets = lambda here, seg: 1 / 0  # 앞 조각의 판정이 죽는다
        try:
            found = merge_gate.problems("git push origin feat/x; gh pr merge 3", self.wt)
        finally:
            merge_gate.git_targets = broken
        self.assertTrue(found)

    def test_없는_폴더의_git_조각이_훅을_죽이지_않는다(self):
        self.denied("cd /nonexistent/fade-x && git merge feat/x; gh pr merge 3", self.wt)
        self.denied("git -C /nonexistent/fade-x push origin HEAD:main; gh pr merge 3", self.wt)


class ParseTest(Repo):
    """따옴표로 묶은 글자는 리다이렉트도 명령 구분도 아니다. 리다이렉트에 붙은 fd 번호는 인자가 아니다.
    따옴표 친 heredoc 의 끝 글에 - 나 . 이 있어도 본문은 명령이 아니다."""

    def seg(self, command, cwd=None):
        import merge_gate
        return [seg for _, seg in merge_gate.located(command, cwd or self.main)]

    def test_따옴표로_묶은_리다이렉트_글자는_인자로_남는다(self):
        import merge_gate
        self.assertEqual(self.seg('git merge -m ">" feat/x'), [["git", "merge", "-m", ">", "feat/x"]])
        self.denied('git merge -m ">" feat/x', self.main)
        self.denied("git merge -m '>>' feat/x", self.main)
        merge = self.seg('gh pr merge --body ">" 3')[0]
        self.assertEqual(merge_gate.pr_target(merge[3:]), (["3"], []))
        self.assertEqual(self.seg('git commit -m "a;b|c&d" && echo x'), [["git", "commit", "-m", "a;b|c&d"], ["echo", "x"]])

    def test_리다이렉트에_붙은_fd_번호는_PR_번호가_아니다(self):
        import merge_gate
        segs = self.seg("gh pr merge --squash 2>&1 | tail -1")
        self.assertEqual(segs[0], ["gh", "pr", "merge", "--squash"])
        self.assertEqual(merge_gate.pr_target(segs[0][3:]), ([], []))

    def test_폴더를_몰라도_base_를_적은_push_는_세션_폴더의_기록으로_본다(self):
        self.denied("cd /nonexistent/fade-x; git push origin HEAD:main", self.wt)
        self.denied('cd "$WT" && git push origin HEAD:refs/heads/main', self.wt)
        self.assertIsNone(self.gate("cd /nonexistent/fade-x; git push origin HEAD", self.wt))

    def test_따옴표_친_heredoc_의_끝_글에_하이픈이나_점이_있어도_본문은_명령이_아니다(self):
        for command in ("cat > n.md <<'END-NOTES'\ngit merge feat/x\nEND-NOTES",
                        'cat > n.md << "A.B"\ngit merge feat/x\nA.B', "cat > n.md <<-'X-1'\n\tgit merge feat/x\n\tX-1"):
            self.assertIsNone(self.gate(command, self.main), command)
        self.denied("cat > n.md <<'END-NOTES'\nbody\nEND-NOTES\ngit merge feat/x", self.main)

    def test_명령_치환_안의_heredoc_본문은_따옴표가_홀수여도_명령이_아니다(self):
        # git commit -m "$(cat <<'EOF' ... EOF )" 는 커밋 메시지의 표준 꼴이다. 본문의 따옴표나 명령 같은 줄에 흔들리지 않는다
        msg = "git commit -m \"$(cat <<'EOF'\nsay \"hi\ngit merge feat/x\nEOF\n)\""
        self.assertEqual(self.seg(msg)[0][:3], ["git", "commit", "-m"])
        self.assertEqual(len(self.seg(msg)), 1)
        self.assertIsNone(self.gate(msg, self.main))
        self.denied(msg + " && git merge feat/x", self.main)
        # 여러 줄 따옴표 글 안의 <<EOF 글자는 heredoc 이 아니다. 뒤 줄을 삼키지 않는다
        self.denied('git commit -m "a\nuse <<EOF here\nb"\ngit merge feat/x', self.main)

    def test_달러_작은따옴표와_백틱_치환_안의_heredoc_도_훅을_죽이지_않는다(self):
        for command in ("printf $'it\\'s'\ncat > n.md <<'EOF'\nsay \"hi\nEOF\ngit push origin HEAD:main",
                        'git commit -m "`cat <<\'EOF\'\nsay "hi\nEOF\n`" && git push origin HEAD:main',
                        "git commit -m \"$(cat <<'EOF'\nsay \"hi\nEOF)\" && git push origin HEAD:main"):
            self.denied(command, self.wt)

    def test_명령_치환_밖의_heredoc_은_끝_글_뒤_괄호_줄에서_끝나지_않는다(self):
        self.denied("cat > n.md <<EOF\nEOF) it's fine\nEOF\ngit merge feat/x", self.main)

    def test_따옴표_없는_heredoc_끝_글에_하이픈이_있어도_그_줄까지가_본문이다(self):
        self.assertIsNone(self.gate("cat > n.md <<END-NOTES\ngit merge feat/x\nEND-NOTES", self.main))
        self.denied("cat > n.md <<END-NOTES\nbody\nEND-NOTES\ngit merge feat/x", self.main)

    def test_감싸는_명령과_그_옵션_뒤의_병합도_본다(self):
        for command in ("timeout 60 gh pr merge 3 --squash", "timeout -k 5 60 gh pr merge 3", "nice -n 5 git merge feat/x",
                        "time -p git merge feat/x", "sudo -u root git merge feat/x", "env -i git merge feat/x",
                        "env -u X FOO=1 git merge feat/x"):
            self.denied(command, self.main)

    def test_폴더를_알_수_없는_cd_뒤의_병합은_세션_폴더로_본다(self):
        for command in ("cd /nonexistent; git merge feat/x", "cd /nonexistent || git merge feat/x",
                        "cd /nonexistent\ngit merge feat/x"):
            self.denied(command, self.main)

    def test_산술의_시프트와_따옴표_안의_꺾쇠_둘은_heredoc_이_아니다(self):
        for command in ("echo $((1<<2))\ngit merge feat/x", "n=$((1<<bits))\ngit merge feat/x", "((x<<=y))\ngit merge feat/x",
                        "echo $(( (1<<n) + 1 ))\ngit merge feat/x",
                        'git commit -m "use a<<b"\ngit merge feat/x',
                        "python3 -c 'print(1 << 2)'\ngit merge feat/x"):
            self.denied(command, self.main)
        self.assertIsNone(self.gate("cat <<END_NOTES\ngit merge feat/x\nEND_NOTES", self.main))


class RedirectNumberTest(Repo):
    """리다이렉트에 붙은 숫자(2>&1 의 2)만 fd 번호다. 띄어 쓴 숫자(gh pr merge 3 >/dev/null 의 3)는 PR 번호로 남는다."""

    def test_리다이렉트_앞에_띄어_쓴_PR_번호를_지우지_않는다(self):
        # PR 3 을 물을 때만 브랜치를 답하는 gh. 번호 없이 물으면(지금 브랜치 main 의 PR) 아무것도 답하지 않는다
        gh = os.path.join(self.bin.name, "gh")
        with open(gh, "w") as f:
            f.write("#!/bin/sh\ncase \"$*\" in\n  \"pr view 3 \"*headRefName*) echo feat/x ;;\nesac\nexit 0\n")
        os.chmod(gh, 0o755)
        env = dict(os.environ, PATH=self.bin.name + os.pathsep + os.environ["PATH"])
        for command in ("gh pr merge 3 >/dev/null 2>&1", "gh pr merge 3 > log", 'gh pr merge "3">/dev/null', "gh pr merge '3'>log"):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.main,
                       "tool_input": {"command": command}}
            r = hook(GATE, json.dumps(payload), env=env)
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
        r = hook(PERMISSION, json.dumps(payload))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")


if __name__ == "__main__":
    unittest.main()
