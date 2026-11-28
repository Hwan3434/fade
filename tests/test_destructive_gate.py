"""파괴적 명령 차단 훅의 판정만 본다. 명령은 어느 것도 실행하지 않고, 훅에 JSON 입력만 넣는다."""
import json
import os
import subprocess
import tempfile
import unittest

from helpers import DESTRUCTIVE, git_repo, hook


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

    def gate(self, command, cwd=None, tool="Bash", crash=False):
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": cwd or self.cwd,
                   "tool_input": {"command": command}}
        r = hook(DESTRUCTIVE, json.dumps(payload), env=dict(os.environ, HOME=self.home), crash=crash)
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

    def test_셸_예약어와_감싸는_명령_뒤의_명령도_본다(self):
        repo = self.repo()
        for command in ("if [ -d x ]; then rm -rf ~; fi", "if rm -rf ~; then echo; fi", "while true; do rm -rf /; done",
                        "{ rm -rf ~; }", "! rm -rf ~", "env rm -rf ~", "env FOO=1 rm -rf ~", "command rm -rf ~",
                        "time rm -rf /", "nohup rm -rf ~", "exec rm -rf ~", "sudo FOO=1 rm -rf /"):
            self.assertBlocked(command)
        self.assertBlocked("for b in x; do git push -f origin main; done", cwd=repo)
        self.assertAllowed("if [ -d build ]; then rm -rf build; fi")
        self.assertAllowed("for d in a b; do rm -rf ~/tmp/$d; done")

    def test_같은_명령_안의_cd_를_따라간다(self):
        self.assertBlocked("cd ~ && rm -rf *")
        self.assertBlocked("cd && rm -rf .")
        self.assertBlocked("cd /tmp; cd ~; rm -rf *")
        self.assertAllowed("cd " + self.cwd + " && rm -rf *")  # /tmp 는 CI 에서 가짜 홈의 위 폴더라 쓰지 않는다
        self.assertAllowed("cd ~/projects && rm -rf build")

    def test_cd_에_리다이렉트가_붙어도_cd_의_첫_인자를_폴더로_본다(self):
        for command in ("cd ~ >/dev/null 2>&1 && rm -rf *", "cd ~ 2>/dev/null && rm -rf .", "cd ~ > /dev/null; rm -rf .",
                        "cd $HOME 2>&1 && rm -rf *", "cd ${HOME} >/dev/null && rm -rf .", "cd ~ 1>&2 && rm -rf *"):
            self.assertBlocked(command)
        self.assertAllowed("cd " + self.cwd + " >/dev/null 2>&1 && rm -rf *")

    def test_폴더를_알_수_없는_cd_뒤에는_그_폴더째_지우는_삭제를_막는다(self):
        # 셸 변수는 비어 있으면 cd 가 홈으로 가고, 없는 폴더로의 cd 가 실패하면 ; 뒤의 rm 은 앞 폴더에서 돈다
        for command in ('cd "$WT" && rm -rf .', "cd $X && rm -rf *", 'cd "$WT"; rm -rf ..',
                        'cd "$WT" && rm -rf ./', 'cd "$WT" && rm -rf a/../..'):
            self.assertBlocked(command)
        for command in ('cd "$WT" && rm -rf .fade-review/parts', 'cd "$WT" && rm -rf build *.log',
                        'cd "$WT" && rm -rf ' + os.path.join(self.cwd, "x"), "cd /no/such/dir && rm -f *"):
            self.assertAllowed(command)

    def test_같은_줄에서_만든_폴더로_cd_한_뒤의_삭제는_그_폴더로_본다(self):
        # 글자로 적은 경로는 아직 없어도 그 경로로 푼다. 알 수 없는 것은 셸 변수와 명령 치환뿐이다
        self.assertAllowed("mkdir -p out && cd out && rm -rf *")
        self.assertAllowed("mkdir -p out && cd out &&\nrm -rf *")
        self.assertBlocked("cd ~/no-such-dir/.. && rm -rf *")

    def test_없는_폴더로의_cd_가_실패해도_이어_도는_rm_은_앞_폴더에서_본다(self):
        # ; || 줄바꿈 뒤의 rm 은 cd 가 실패해도 돈다. 그때 글자 그대로의 경로로 풀면 홈 삭제를 놓친다
        for command in ("cd ~/no-such-typo 2>/dev/null; rm -rf .*", "cd build || true; rm -rf *", "cd nope\nrm -rf .",
                        "cd /no/such/dir; rm -rf .*"):
            self.assertBlocked(command, cwd=self.home)

    def test_현재_폴더_변수로_가리킨_홈_삭제도_막는다(self):
        for command in ('rm -rf "$PWD"', "rm -rf ${PWD}/*", 'rm -rf "$(pwd)"'):
            self.assertBlocked(command, cwd=self.home)
        self.assertAllowed('rm -rf "$PWD/build"', cwd=self.home)
        self.assertBlocked('cd "$X"; rm -rf "$PWD"', cwd=self.home)  # 폴더를 알 수 없으면 $PWD 도 알 수 없는 폴더다
        self.assertBlocked("cat > n.md <<EOF\nEOF) it's\nEOF\nrm -rf ~")

    def test_감싸는_명령과_그_옵션_뒤의_삭제도_본다(self):
        for command in ("timeout 5 rm -rf ~", "sudo -u root rm -rf ~", "env -i rm -rf ~", "nice -n 10 rm -rf ~",
                        "time -p rm -rf ~", "sudo -E rm -rf /"):
            self.assertBlocked(command)

    def test_명령_치환_안의_heredoc_본문에_홀수_따옴표가_있어도_뒤의_홈_삭제를_막는다(self):
        self.assertBlocked("git commit -m \"$(cat <<'EOF'\nsay \"hi\nEOF\n)\" && cd ~ && rm -rf *")

    def test_삭제_훅은_병합_훅과_같은_명령_해석을_쓴다(self):
        with open(DESTRUCTIVE, encoding="utf-8") as f:
            src = f.read()
        self.assertTrue("merge_gate.located(" in src)
        self.assertFalse('name == "cd"' in src)  # cd 를 따로 해석하면 두 훅이 다시 어긋난다

    def test_끝_이름의_글롭은_그_폴더_안_전부로_본다(self):
        self.assertBlocked("rm -rf ~/.*")
        self.assertBlocked("rm -rf ~/.[!.]*")
        self.assertBlocked("rm -rf ~/.ssh/id_*")
        self.assertAllowed("rm -rf ~/*.bak")  # 이름이 걸린 글롭은 폴더 전체가 아니다
        self.assertAllowed("cd ~/proj* && rm -rf build")
        self.assertAllowed("rm -rf ~/logs/*.log")
        self.assertAllowed("rm -rf /tmp/x?")

    def test_모든_브랜치를_force_로_올리면_막는다(self):
        repo = self.repo()
        for command in ("git push --mirror origin", "git push --all -f origin", "git push --force --branches origin"):
            self.assertBlocked(command, cwd=repo)
        self.assertAllowed("git push --all origin", cwd=repo)

    def test_주석은_그_줄_끝까지만_뺀다(self):
        self.assertBlocked("cd /tmp  # 설명\nrm -rf ~")  # 주석 뒤 줄바꿈이 사라지면 다음 줄이 앞 명령에 붙는다
        self.assertBlocked("echo a#b; rm -rf ~")  # 낱말 가운데의 # 는 주석이 아니다
        self.assertBlocked("echo '#'; rm -rf ~")
        self.assertAllowed("ls # ; rm -rf ~")
        self.assertAllowed("# rm -rf ~")

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
        r = hook(DESTRUCTIVE, json.dumps(payload))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_입력이_깨지거나_명령을_해석하지_못하면_판정하지_않는다(self):
        r = hook(DESTRUCTIVE, "{깨진", crash=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertIsNone(self.gate('rm -rf "/', crash=True))  # 닫히지 않은 따옴표


if __name__ == "__main__":
    unittest.main()
