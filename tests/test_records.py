"""기록이 공개 PR 에 사용자명을 올리지 않고, 실수 기록이 진짜 실수만 받고 묶이게 한다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GATE, PERMISSION, ROOT, commit_and_switch, fake_gh, git_repo, job, mistakes


def git_dir(cwd):
    return subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True,
                          text=True).stdout.strip()


def try_file(cwd, name="out.txt"):
    """tester 가 남기는 자리(git 폴더 안 fade-try/)의 파일."""
    folder = os.path.join(git_dir(cwd), "fade-try")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    open(path, "w").close()
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        commit_and_switch(self.cwd, "feat/x")
        self.home = tempfile.TemporaryDirectory()  # 진짜 홈의 실수 기록에 닿지 않게 홈도 바꾼다
        self.addCleanup(self.home.cleanup)
        self.assertEqual(job(self.cwd, "start", "작업", "--unattended").returncode, 0)

    def own_log(self):
        path = os.path.join(self.home.name, "log", "mistakes.jsonl")
        return path, dict(os.environ, FADE_MISTAKES=path)

    def no_log_env(self, home=None):
        """FADE_MISTAKES 를 정하지 않은 환경. 홈은 임시 폴더라 ~/.claude/fade 가 진짜 홈이 아니다."""
        env = {k: v for k, v in os.environ.items() if k != "FADE_MISTAKES"}
        env["HOME"] = home or self.home.name
        return env

    def default_log(self, home=None):
        return os.path.join(home or self.home.name, ".claude", "fade", "mistakes.jsonl")


class MaskTest(Base):
    """show 는 공개 PR 의 기록 댓글로 간다. 사용자명이 든 경로를 두 꼴 모두 가린다."""

    def show_with_home(self, home, text):
        job(self.cwd, "log", "기준", "echo " + text, env=dict(os.environ, HOME=home))
        return job(self.cwd, "show", "--full", env=dict(os.environ, HOME=home)).stdout

    def test_임시_폴더_이름에_든_사용자명을_가린다(self):
        out = self.show_with_home("/Users/fade-user", "/private/tmp/claude-501/-Users-fade-user-workspace-x/a.txt")
        self.assertNotIn("fade-user", out)
        self.assertIn("/private/tmp/claude-501/-~-workspace-x/a.txt", out)

    def test_점과_밑줄이_든_홈도_가린다(self):
        # Claude 는 폴더 이름을 만들 때 영숫자가 아닌 글자를 모두 - 로 바꾼다 (/Users/a.b_c → -Users-a-b-c)
        out = self.show_with_home("/Users/a.b_c", "/tmp/claude-501/-Users-a-b-c--claude/x /Users/a.b_c/y")
        self.assertNotIn("a-b-c", out)
        self.assertNotIn("a.b_c", out)
        self.assertIn("/tmp/claude-501/-~--claude/x ~/y", out)

    def test_이름이_더_긴_다른_사용자는_건드리지_않는다(self):
        out = self.show_with_home("/Users/ab", "-Users-abc-x /Users/abc/y /Users/ab")
        self.assertIn("-Users-abc-x /Users/abc/y ~", out)


class TempRepoTest(Base):
    """OS 임시 폴더의 레포(테스트, 써 보기)는 FADE_MISTAKES 를 정하지 않으면 진짜 실수 기록에 쓰지 않는다."""

    def test_stop_과_slip_은_임시_레포에서_기본_실수_기록에_쓰지_않는다(self):
        env = self.no_log_env()
        r = job(self.cwd, "slip", "user", "branch-name", "브랜치 이름을 어겼다", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("임시 폴더", r.stdout)
        self.assertEqual(job(self.cwd, "stop", "멈춤", env=env).returncode, 0)
        self.assertFalse(os.path.exists(self.default_log()))

    def test_FADE_MISTAKES_를_정하면_임시_레포에서도_쓴다(self):
        path, env = self.own_log()
        self.assertEqual(job(self.cwd, "slip", "user", "branch-name", "지적", env=env).returncode, 0)
        self.assertEqual(len(mistakes(path)), 1)

    def test_macOS_의_tmp_링크_아래_레포도_임시_레포다(self):
        if not os.path.isdir("/tmp"):
            self.skipTest("/tmp 가 없다")
        d = tempfile.TemporaryDirectory(dir="/tmp")  # macOS 에서 /tmp 는 /private/tmp 를 가리키는 링크다
        self.addCleanup(d.cleanup)
        subprocess.run(["git", "init", "-q", d.name], check=True)
        commit_and_switch(d.name, "feat/x")
        job(d.name, "start", "작업")
        self.assertEqual(job(d.name, "slip", "user", "k", "지적", env=self.no_log_env()).returncode, 0)
        self.assertFalse(os.path.exists(self.default_log()))

    def hook(self, script, payload, env):
        payload = dict(payload, cwd=self.cwd)
        r = subprocess.run([sys.executable, script], input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]

    def test_훅도_임시_레포에서는_기본_실수_기록에_쓰지_않고_막기는_한다(self):
        env = self.no_log_env()
        bin_ = tempfile.TemporaryDirectory()  # 검사 줄이 없는 가짜 gh. PATH 에서 폴더를 빼면 같은 폴더의 git 도 사라진다
        self.addCleanup(bin_.cleanup)
        env["PATH"] = fake_gh(bin_.name, 0) + os.pathsep + env["PATH"]
        gate = self.hook(GATE, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                "tool_input": {"command": "gh pr merge 3 --squash"}}, env)
        self.assertEqual(gate["permissionDecision"], "deny")
        ask = self.hook(PERMISSION, {"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                     "tool_input": {"command": "git rebase origin/main"}}, env)
        self.assertEqual(ask["decision"]["behavior"], "deny")
        self.assertFalse(os.path.exists(self.default_log()))

    def test_임시_폴더_밖의_레포는_기본_실수_기록에_쓴다(self):
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        if any(os.path.realpath(common).startswith(os.path.realpath(t) + os.sep)
               for t in (tempfile.gettempdir(), "/tmp")):
            self.skipTest("이 체크아웃이 임시 폴더 아래에 있다")
        outside = tempfile.TemporaryDirectory(dir=common)  # 이 체크아웃의 git 폴더는 임시 폴더가 아니다
        self.addCleanup(outside.cleanup)
        subprocess.run(["git", "init", "-q", outside.name], check=True)
        commit_and_switch(outside.name, "feat/x")
        job(outside.name, "start", "작업")
        self.assertEqual(job(outside.name, "slip", "user", "k", "지적", env=self.no_log_env()).returncode, 0)
        self.assertEqual([m["what"] for m in mistakes(self.default_log())], ["지적"])


class SlipKeyTest(Base):
    """slip 은 같은 실수끼리 묶는 이름(key)을 받는다. hardener 가 돌지 않아도 묶인다."""

    def test_slip_은_key_를_받아_그_줄에_적는다(self):
        path, env = self.own_log()
        r = job(self.cwd, "slip", "review", "empty-list-index", "빈 목록에서 첫 원소를 읽었다", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = mistakes(path)[0]
        self.assertEqual((row["source"], row["key"], row["what"]), ("review", "empty-list-index", "빈 목록에서 첫 원소를 읽었다"))

    def test_key_없이_부르면_받지_않고_있는_key_를_알린다(self):
        path, env = self.own_log()
        job(self.cwd, "slip", "ci", "py312-syntax", "3.12 에 없는 문법", env=env)
        r = job(self.cwd, "slip", "user", "PR 본문에 번호를 썼다", env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("py312-syntax", r.stderr)
        self.assertEqual(len(mistakes(path)), 1)

    def test_key_는_영문_소문자_숫자_하이픈이다(self):
        path, env = self.own_log()
        for key in ("Upper", "한글", "a b", "a_b", "-a", ""):
            self.assertNotEqual(job(self.cwd, "slip", "user", key, "지적", env=env).returncode, 0, key)
        self.assertEqual(mistakes(path), [])

    def test_같은_key_가_몇_번째인지_알린다(self):
        path, env = self.own_log()
        job(self.cwd, "slip", "user", "pr-number", "첫째", env=env)
        out = job(self.cwd, "slip", "review", "pr-number", "둘째", env=env).stdout
        self.assertIn("2번째", out)
        self.assertLessEqual(len(out.splitlines()), 2)

    def test_tester_가_찾은_버그는_try_로_남긴다(self):
        path, env = self.own_log()
        self.assertEqual(job(self.cwd, "slip", "try", "empty-input", "빈 입력에서 죽었다", env=env).returncode, 0)
        self.assertEqual(mistakes(path)[0]["source"], "try")

    def test_slip_은_job_기록에도_남는다(self):
        # 임시 레포라 실수 기록 파일에 쓰지 않아도, 이 작업에서 slip 이 있었다는 것은 job 기록에 남는다
        job(self.cwd, "slip", "review", "k", "지적", env=self.no_log_env())
        with open(os.path.join(git_dir(self.cwd), "fade-job.json"), encoding="utf-8") as f:
            slips = json.load(f)["slips"]
        self.assertEqual([(s["source"], s["key"], s["what"]) for s in slips], [("review", "k", "지적")])


class PrFillTest(Base):
    """리뷰 slip 은 PR 을 열기 전에 찍힌다. PR 을 기록하면 이 작업의 줄에 PR 을 채운다."""

    def test_pr_을_기록하면_이_작업의_빈_pr_칸을_채운다(self):
        path, env = self.own_log()
        job(self.cwd, "slip", "review", "k", "리뷰 지적", env=env)
        self.assertEqual(job(self.cwd, "pr", "https://github.com/o/r/pull/7", env=env).returncode, 0)
        self.assertEqual(mistakes(path)[0]["pr"], "https://github.com/o/r/pull/7")

    def test_같은_브랜치_이름의_예전_작업_줄과_다른_레포의_줄은_바꾸지_않는다(self):
        path, env = self.own_log()
        old = {"time": "2020-01-01T00:00:00+0000", "repo": os.path.realpath(self.cwd), "branch": "feat/x", "pr": "",
               "source": "review", "what": "예전", "key": "k", "handled": ""}
        other = dict(old, time="2999-01-01T00:00:00+0000", repo="/elsewhere", what="다른 레포")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(old, ensure_ascii=False) + "\n" + json.dumps(other, ensure_ascii=False) + "\n")
        job(self.cwd, "slip", "review", "k", "이번", env=env)
        job(self.cwd, "pr", "https://github.com/o/r/pull/7", env=env)
        self.assertEqual([(m["what"], m["pr"]) for m in mistakes(path)],
                         [("예전", ""), ("다른 레포", ""), ("이번", "https://github.com/o/r/pull/7")])

    def test_이미_pr_이_있는_줄은_그대로다(self):
        path, env = self.own_log()
        job(self.cwd, "pr", "https://github.com/o/r/pull/7", env=env)
        job(self.cwd, "slip", "ci", "k", "CI", env=env)
        job(self.cwd, "pr", "https://github.com/o/r/pull/8", env=env)
        self.assertEqual(mistakes(path)[0]["pr"], "https://github.com/o/r/pull/7")


class LockTest(Base):
    """실수 기록은 여러 세션이 함께 쓴다. 다시 쓰는 명령(pr, mark)은 붙이는 쪽과 같은 잠금을 잡아 그 사이 붙은 줄을 잃지 않는다."""

    def test_pr_은_잠금을_기다리고_그_사이_붙은_줄을_지킨다(self):
        import fcntl
        path, env = self.own_log()
        job(self.cwd, "slip", "review", "k", "이번", env=env)
        with open(path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            p = subprocess.Popen([sys.executable, os.path.join(ROOT, "skills", "job", "job.py"), "pr",
                                  "https://github.com/o/r/pull/7"], cwd=self.cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            try:
                p.wait(timeout=1.5)
                self.fail("pr 이 잠금을 기다리지 않았다")
            except subprocess.TimeoutExpired:
                pass
            with open(path, "a", encoding="utf-8") as f:  # 잠금을 잡은 다른 세션이 붙인 줄
                f.write(json.dumps({"time": "2999-01-01T00:00:00+0000", "repo": "/elsewhere", "branch": "b", "pr": "",
                                    "source": "ci", "what": "다른 세션", "key": "k", "handled": ""}) + "\n")
        self.assertEqual(p.wait(timeout=30), 0, p.stderr.read())
        self.assertEqual([(m["what"], m["pr"]) for m in mistakes(path)],
                         [("이번", "https://github.com/o/r/pull/7"), ("다른 세션", "")])


class TempFileTest(Base):
    """세션 임시 폴더의 화면·출력 파일은 지워질 수 있다. 레포 밖 임시 폴더의 파일은 증거로 받지 않는다."""

    def test_레포_밖_임시_폴더의_파일은_받지_않는다(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "shot.png")
        open(path, "w").close()
        for args in (("tried", "써 봄", path), ("evidence", "기준", path)):
            r = job(self.cwd, *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("fade-try", r.stderr)

    def test_git_폴더_안_fade_try_의_파일은_받는다(self):
        self.assertEqual(job(self.cwd, "tried", "써 봄", try_file(self.cwd)).returncode, 0)
        self.assertEqual(job(self.cwd, "evidence", "기준", try_file(self.cwd, "b.txt")).returncode, 0)


class ReportOrderTest(Base):
    """보고 첫 줄은 기록이 남은 곳의 주소다. 답 없는 질문은 그다음이다."""

    def test_답_없는_질문의_안내는_기록_주소_다음이라고_말한다(self):
        job(self.cwd, "ask", "배포도 할까")
        show = job(self.cwd, "show").stdout.splitlines()
        self.assertEqual(show[1], "답을 받지 못한 질문 (보고의 첫 줄인 기록 주소 다음에 번호째 다시 적는다):")
        said = job(self.cwd, "no-test", "이유").stdout
        self.assertIn("보고의 첫 줄인 기록 주소 다음에", said)
        self.assertNotIn("맨 위", said)

    def test_job_의_보고_절은_기록_주소를_첫_줄에_둔다(self):
        with open(os.path.join(ROOT, "skills", "job", "SKILL.md"), encoding="utf-8") as f:
            report = [line for line in f if line.startswith("8. **보고**")][0]
        self.assertIn("보고 첫 줄에는 그 댓글의 주소", report)
        self.assertLess(report.index("보고 첫 줄에는 그 댓글의 주소"), report.index("답을 받지 못한 질문"))


if __name__ == "__main__":
    unittest.main()
