"""기록 명령은 무엇을 기록했는지 한두 줄만 찍는다. 기록 전체는 show, 빠진 것은 check 에서만 나온다.
`job.py`, `nonstop.py` 는 플러그인의 bin/ 을 거쳐 경로 없이 부른다."""
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT, commit_and_switch, git_repo, job

BIN = os.path.join(ROOT, "bin")
NONSTOP = os.path.join(ROOT, "skills", "nonstop", "nonstop.py")
WHOLE = ("## 작업 기록", "병합 전에 빠진 것", "상태:")  # show 의 머리, 빠진 것 목록, 상태 줄


class RecordOutputTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        self.out = tempfile.TemporaryDirectory()  # 스크린샷 같은 증거 파일은 레포 밖에 둔다
        self.addCleanup(self.out.cleanup)
        commit_and_switch(self.cwd, "feat/x")

    def shot(self, name="shot.png"):
        path = os.path.join(self.out.name, name)
        open(path, "w").close()
        return path

    def short(self, *args):
        """기록 명령을 돌려 성공했는지, 두 줄 이하인지, 기록 전체와 빠진 것을 찍지 않았는지 보고 출력을 돌려준다."""
        r = job(self.cwd, *args)
        self.assertEqual(r.returncode, 0, (args, r.stderr))
        lines = r.stdout.splitlines()
        self.assertTrue(1 <= len(lines) <= 2, (args, r.stdout))
        for word in WHOLE:
            self.assertNotIn(word, r.stdout, args)
        return r.stdout

    def test_기록_명령은_무엇을_기록했는지_두_줄_이하로만_찍는다(self):
        self.assertIn("job 의 출력을 줄인다", self.short("start", "job 의 출력을 줄인다", "--unattended"))
        self.short("scope", "pr")
        self.short("scope", "merge")
        self.assertIn("test -f done.txt", self.short("red", "test -f done.txt"))
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        self.short("green")
        self.short("no-test", "장치 없음")
        self.assertIn("기준 1", self.short("evidence", "기준 1", self.shot()))
        self.assertIn("기준 2", self.short("log", "기준 2", "echo 실제=3"))
        self.short("tried", "명령으로 써 봄", self.shot("try.png"))
        self.short("drop", "기준 1")
        self.short("drop", "--tried")
        self.short("try-na", "써 볼 화면도 명령도 없다")
        self.short("human", "앱 화면은 사람이 본다")
        self.assertIn("0", self.short("review", "0", "작은 변경이라 버그 축만"))
        self.assertIn("양쪽 문", self.short("door", "two-way", "revert 하면 돌아간다"))
        self.short("pr", "https://github.com/o/r/pull/7")
        self.short("slip", "user", "PR 본문에 번호를 썼다")
        self.short("stop", "같은 실패를 두 번 고쳐도 남는다")
        self.assertIn("abc1234", self.short("merged", "abc1234", "base CI 통과"))

    def test_start_는_범위와_사람_없음을_한_줄에_알린다(self):
        out = self.short("start", "제목", "--unattended", "--pr-only")
        self.assertIn("PR 까지", out)
        self.assertIn("사람 없음", out)

    def test_log_는_성공하면_명령_출력을_찍지_않고_종료_코드와_로그_경로만_알린다(self):
        self.short("start", "작업")
        out = self.short("log", "기준", "seq 1 60 | sed s/^/줄=/")
        self.assertNotIn("줄=60", out)  # 명령 글이 아니라 출력에만 나오는 글자
        self.assertIn("종료 코드 0", out)
        self.assertIn("01.log", out)

    def test_log_는_명령이_실패하면_원인을_알_만큼_출력_끝을_찍는다(self):
        self.short("start", "작업")
        r = job(self.cwd, "log", "기준", "seq 1 100; echo 원인=디스크가 가득 찼다; exit 3")
        self.assertEqual(r.returncode, 0, r.stderr)  # 실패한 명령도 증거로 기록한다
        self.assertIn("종료 코드 3", r.stdout)
        self.assertIn("원인=디스크가 가득 찼다", r.stdout)
        self.assertNotIn("\n1\n", r.stdout)  # 출력 전체가 아니라 끝만 찍는다
        for word in WHOLE:
            self.assertNotIn(word, r.stdout)

    def test_답_없는_질문이_있으면_기록_명령_뒤에_그_사실을_한_줄_남긴다(self):
        self.short("start", "작업")
        r = job(self.cwd, "ask", "A 와 B 중 무엇으로 할까")
        self.assertEqual(r.returncode, 0, r.stderr)
        job(self.cwd, "ask", "배포도 할까")
        r = job(self.cwd, "evidence", "기준", self.shot())
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        notice = [line for line in lines if "답을 받지 못한 질문" in line]
        self.assertEqual(len(notice), 1, r.stdout)
        self.assertIn("2개", notice[0])
        self.assertLessEqual(len(lines), 3, r.stdout)
        job(self.cwd, "answered", "1", "A")
        job(self.cwd, "answered", "2", "하지 않는다")
        self.assertNotIn("답을 받지 못한 질문", self.short("door", "two-way", "revert 하면 돌아간다"))


class ShowCheckTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        commit_and_switch(self.cwd, "base")

    def test_show_는_빠진_것을_찍지_않고_check_만_찍는다(self):
        commit_and_switch(self.cwd, "feat/x")
        job(self.cwd, "start", "작업")
        show = job(self.cwd, "show").stdout + job(self.cwd, "show", "--full").stdout
        self.assertNotIn("병합 전에 빠진 것", show)
        self.assertNotIn("증거: 완료 기준에 붙인 로그나 스크린샷이 없다", show)
        check = job(self.cwd, "check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("증거: 완료 기준에 붙인 로그나 스크린샷이 없다", check.stdout)

    def test_show_save_는_전문을_워크트리가_지워져도_남는_파일에_쓰고_절대_경로를_찍는다(self):
        wt = os.path.join(self.cwd, "wt")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "feat/x", wt], cwd=self.cwd, check=True)
        job(wt, "start", "작업")
        job(wt, "log", "기준", "echo 실제=3")
        full = job(wt, "show", "--full").stdout
        r = job(wt, "show", "--save")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 1, r.stdout)
        path = r.stdout.strip().split()[-1]
        self.assertTrue(os.path.isabs(path), path)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), full)
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=self.cwd, check=True)
        self.assertTrue(os.path.isfile(path), path)
        common = os.path.realpath(os.path.join(self.cwd, ".git"))
        self.assertTrue(os.path.realpath(path).startswith(common + os.sep), path)


class BinTest(unittest.TestCase):
    """bin/ 은 플러그인이 켜져 있으면 Claude Code 가 Bash 도구의 PATH 에 두는 폴더다."""

    def run_bin(self, cwd, *args, env=None):
        env = dict(env or os.environ)
        env["PATH"] = BIN + os.pathsep + env["PATH"]
        return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=env)

    def test_bin_의_입구는_git_이_실행_파일로_담는다(self):
        for name in ("job.py", "nonstop.py"):
            mode = subprocess.run(["git", "ls-files", "-s", "bin/" + name], cwd=ROOT, capture_output=True,
                                  text=True).stdout.split()
            self.assertEqual(mode[:1], ["100755"], name)
            self.assertTrue(os.access(os.path.join(BIN, name), os.X_OK), name)

    def test_경로_없이_부른_job_py_가_본체와_같은_기록을_쓴다(self):
        repo = git_repo()
        self.addCleanup(repo.cleanup)
        commit_and_switch(repo.name, "feat/x")
        r = self.run_bin(repo.name, "job.py", "start", "경로 없이 시작")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("- 작업: 경로 없이 시작", job(repo.name, "show").stdout)
        r = self.run_bin(repo.name, "job.py", "show", "--bogus")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("job.py show", r.stderr)  # 본체의 사용법이 나온다

    def test_경로_없이_부른_nonstop_py_가_본체와_같은_목록을_쓴다(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        env = dict(os.environ, HOME=home.name)
        r = self.run_bin(home.name, "nonstop.py", "init", "s1", "첫 작업", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, NONSTOP, "show", "s1"], capture_output=True, text=True, env=env)
        self.assertIn("1. 첫 작업", r.stdout)


class NonstopOutputTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def run_cmd(self, *args):
        env = dict(os.environ, HOME=self.home.name)
        return subprocess.run([sys.executable, NONSTOP, *args], capture_output=True, text=True, env=env)

    def test_기록_명령은_보고_전체를_찍지_않고_무엇을_했는지와_다음_작업만_알린다(self):
        for args, after in ((("init", "s1", "가", "나", "다"), "다음: 1. 가"), (("add", "s1", "라"), "다음: 1. 가"),
                            (("set", "s1", "1", "done", "https://github.com/o/r/pull/3"), "다음: 2. 나"),
                            (("decide", "s1", "2", "권장안으로 정함"), "다음: 2. 나")):
            r = self.run_cmd(*args)
            self.assertEqual(r.returncode, 0, (args, r.stderr))
            self.assertLessEqual(len(r.stdout.splitlines()), 2, (args, r.stdout))
            self.assertNotIn("## ", r.stdout, args)
            self.assertNotIn("PR 1개", r.stdout, args)
            self.assertIn(after, r.stdout, args)

    def test_show_는_보고_전체를_찍는다(self):
        self.run_cmd("init", "s1", "가")
        self.run_cmd("set", "s1", "1", "done", "https://github.com/o/r/pull/3")
        r = self.run_cmd("show", "s1")
        self.assertIn("## 끝난 것", r.stdout)
        self.assertIn("PR 1개", r.stdout)


if __name__ == "__main__":
    unittest.main()
