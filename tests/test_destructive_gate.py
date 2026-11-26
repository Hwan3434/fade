"""파괴적 명령 차단 훅의 판정만 본다. 명령은 어느 것도 실행하지 않고, 훅에 JSON 입력만 넣는다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import DESTRUCTIVE, git_repo


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, check=True,
                   capture_output=True)


class DestructiveGateTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()  # 가짜 홈. 훅은 HOME 으로 홈을 판정한다
        self.addCleanup(home.cleanup)
        self.home = home.name
        os.makedirs(os.path.join(self.home, ".ssh"))
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.cwd = work.name

    def gate(self, command, cwd=None, tool="Bash"):
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd or self.cwd,
                   "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, DESTRUCTIVE], input=json.dumps(payload), capture_output=True, text=True,
                           env=dict(os.environ, HOME=self.home))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def assertBlocked(self, command, cwd=None):
        out = self.gate(command, cwd)
        self.assertIsNotNone(out, command)
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "deny", command)
        self.assertTrue(out["permissionDecisionReason"], command)
        return out["permissionDecisionReason"]

    def assertAllowed(self, command, cwd=None):
        self.assertIsNone(self.gate(command, cwd), command)

    # rm

    def test_루트와_홈의_재귀_삭제를_막는다(self):
        for command in ("rm -rf /", "rm -fr /", "rm -r -f /", "rm -Rf /", "rm --recursive --force /",
                        "rm -rf -- /", "rm -rf /*", "rm -rfv /", "rm / -rf", "rm -rf ~", "rm -rf ~/",
                        "rm -rf ~/*", 'rm -rf "$HOME"', "rm -rf ${HOME}", "rm -rf $HOME/",
                        "rm -rf " + self.home, "rm -rf " + self.home + "/", "rm -rf ~/..",
                        "sudo rm -rf /", "/bin/rm -rf ~", "FOO=1 rm -rf ~", "rm -rf /tmp/x ~"):
            self.assertBlocked(command)

    def test_ssh_폴더의_재귀_삭제를_막는다(self):
        for command in ("rm -rf ~/.ssh", "rm -rf ~/.ssh/", "rm -rf $HOME/.ssh/id_ed25519",
                        "rm -rf " + os.path.join(self.home, ".ssh")):
            self.assertBlocked(command)

    def test_재귀_옵션만_있어도_막는다(self):
        self.assertBlocked("rm -r ~")
        self.assertBlocked("rm --recursive /")

    def test_상대_경로는_작업_폴더에서_판정한다(self):
        self.assertBlocked("rm -rf .", cwd=self.home)
        self.assertBlocked("rm -rf *", cwd=self.home)
        self.assertAllowed("rm -rf ./node_modules", cwd=self.home)
        self.assertAllowed("rm -rf .", cwd=self.cwd)

    def test_뒤에_이어진_명령과_다음_줄도_본다(self):
        self.assertBlocked("echo ok && rm -rf ~")
        self.assertBlocked("ls; rm -rf /")
        self.assertBlocked("ls\nrm -rf ~")
        self.assertBlocked("echo $(rm -rf ~)")

    def test_홈_아래_하위_폴더와_다른_경로의_삭제는_막지_않는다(self):
        for command in ("rm -rf ~/projects/tmp", "rm -rf $HOME/Library/Caches/x", "rm -rf build",
                        "rm -rf /tmp/fade-x", "rm -rf ~/.sshx", "rm -f ~/notes.txt", "rm ~", "rm -f /",
                        "rm -rf " + os.path.join(self.home, "work")):
            self.assertAllowed(command)

    def test_인용된_글자와_heredoc_본문은_명령이_아니다(self):
        for command in ('echo "rm -rf /"', "git commit -m 'rm -rf ~ 를 막는다'", "grep -n 'rm -rf' hooks/*.py",
                        "cat > notes.md <<'EOF'\nrm -rf ~\nEOF",
                        'git commit -m "$(cat <<EOF\nrm -rf /\nEOF\n)"'):
            self.assertAllowed(command)

    # force push

    def repo(self, default=None, branch="feat/x"):
        d = git_repo()
        self.addCleanup(d.cleanup)
        git(d.name, "commit", "-q", "--allow-empty", "-m", "x")
        if default:
            git(d.name, "update-ref", "refs/remotes/origin/" + default, "HEAD")
            git(d.name, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/" + default)
        git(d.name, "switch", "-q", "-C", branch)  # git init 의 기본 브랜치와 이름이 같아도 된다
        return d.name

    def test_기본_브랜치로의_force_push_를_막는다(self):
        repo = self.repo()
        for command in ("git push --force origin main", "git push -f origin main", "git push -f origin master",
                        "git push --force-with-lease origin main", "git push --force-with-lease=main:abc origin main",
                        "git push origin +main", "git push origin +HEAD:main", "git push -f origin HEAD:refs/heads/main",
                        "git push -fu origin main", "git push -f origin feat/x main",
                        "git -c push.default=current push -f origin main", "git --no-pager push -f origin main"):
            self.assertBlocked(command, cwd=repo)

    def test_그_레포의_기본_브랜치도_지킨다(self):
        repo = self.repo(default="trunk")
        self.assertBlocked("git push -f origin trunk", cwd=repo)
        self.assertAllowed("git push -f origin trunk", cwd=self.repo())  # 기본 브랜치가 trunk 가 아닌 레포

    def test_git_C_는_그_경로의_레포로_판정한다(self):
        repo = self.repo(default="trunk")
        self.assertBlocked("git -C " + repo + " push -f origin trunk")
        self.assertAllowed("git -C " + repo + " push -f origin feat/x")

    def test_refspec_없는_force_push_는_지금_브랜치로_판정한다(self):
        self.assertBlocked("git push -f", cwd=self.repo(branch="main"))
        self.assertBlocked("git push --force origin", cwd=self.repo(default="trunk", branch="trunk"))
        self.assertAllowed("git push -f", cwd=self.repo(branch="feat/x"))
        self.assertAllowed("git push -f origin HEAD", cwd=self.repo(branch="feat/x"))

    def test_기능_브랜치_force_push_와_보통_push_는_막지_않는다(self):
        repo = self.repo()
        for command in ("git push --force origin feat/x", "git push -f origin feat/x", "git push origin +feat/x",
                        "git push --force-with-lease origin feat/x", "git push origin main", "git push origin +feat/x main",
                        "git push -u origin feat/x", 'echo "git push -f origin main"', "git log --force main"):
            self.assertAllowed(command, cwd=repo)

    # dd, mkfs

    def test_장치에_쓰는_dd_와_mkfs_를_막는다(self):
        for command in ("dd if=/dev/zero of=/dev/disk2 bs=1m", "sudo dd of=/dev/sda if=x.img",
                        "mkfs.ext4 /dev/sdb1", "mkfs -t ext4 /dev/sdb1", "sudo mkfs.vfat /dev/sdc"):
            self.assertBlocked(command)

    def test_장치가_아닌_dd_와_mkfs_글자는_막지_않는다(self):
        for command in ("dd if=/dev/zero of=/dev/null bs=1m count=1", "dd if=a.img of=b.img", "echo mkfs.ext4",
                        "man mkfs", "dd if=/dev/disk2 of=backup.img"):
            self.assertAllowed(command)

    # 모든 세션, 깨진 입력

    def test_job_기록이_없는_곳에서도_막는다(self):
        self.assertBlocked("rm -rf ~")  # self.cwd 는 git 레포도 아니다

    def test_Bash_가_아니거나_명령이_없으면_말하지_않는다(self):
        self.assertIsNone(self.gate("rm -rf ~", tool="Read"))
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd, "tool_input": {}}
        r = subprocess.run([sys.executable, DESTRUCTIVE], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_입력이_깨지거나_명령을_해석하지_못하면_판정하지_않는다(self):
        r = subprocess.run([sys.executable, DESTRUCTIVE], input="{깨진", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertIsNone(self.gate('rm -rf "/'))  # 닫히지 않은 따옴표


if __name__ == "__main__":
    unittest.main()
