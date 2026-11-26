import os
import subprocess
import sys
import unittest

from helpers import JOB, commit_and_switch, git_repo, job


class JobTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name

    def start(self, *extra):
        r = job(self.cwd, "start", "작업", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)

    def shot(self, name="shot.png"):
        path = os.path.join(self.cwd, name)
        with open(path, "wb") as f:
            f.write(b"png")
        return path

    def complete(self):
        """병합 조건을 모두 채운다: red, green, 증거, 써 보기."""
        self.assertEqual(job(self.cwd, "red", "test -f done.txt").returncode, 0)
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        self.assertEqual(job(self.cwd, "green").returncode, 0)
        self.assertEqual(job(self.cwd, "evidence", "기준 1", self.shot()).returncode, 0)
        self.assertEqual(job(self.cwd, "tried", "화면에서 눌러 봄", self.shot("try.png")).returncode, 0)

    def test_시작하지_않으면_다른_명령을_받지_않는다(self):
        r = job(self.cwd, "red", "false")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("start", r.stderr)

    def test_같은_작업을_두_번_시작하지_않는다(self):
        self.start()
        r = job(self.cwd, "start", "또")
        self.assertNotEqual(r.returncode, 0)

    def test_병합이_끝났거나_브랜치가_바뀌면_새_작업을_시작한다(self):
        self.start()
        job(self.cwd, "merged", "abc1234")
        self.assertEqual(job(self.cwd, "start", "다음 작업").returncode, 0)
        commit_and_switch(self.cwd, "other")
        self.assertEqual(job(self.cwd, "start", "다른 브랜치 작업").returncode, 0)

    def test_red_는_실패하는_명령만_기록한다(self):
        self.start()
        r = job(self.cwd, "red", "true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("실패하지 않는다", r.stderr)
        self.assertEqual(job(self.cwd, "red", "false").returncode, 0)

    def test_green_은_red_명령이_통과해야_기록한다(self):
        self.start()
        self.assertNotEqual(job(self.cwd, "green").returncode, 0)  # red 전
        job(self.cwd, "red", "test -f done.txt")
        r = job(self.cwd, "green")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("통과하지 않는다", r.stderr)
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        self.assertEqual(job(self.cwd, "green").returncode, 0)

    def test_증거와_써_보기_파일은_있어야_한다(self):
        self.start()
        self.assertNotEqual(job(self.cwd, "evidence", "기준", "/없는/파일.png").returncode, 0)
        self.assertNotEqual(job(self.cwd, "tried", "써 봄").returncode, 0)  # 파일 없음

    def test_log_는_명령_출력을_파일로_남긴다(self):
        self.start()
        r = job(self.cwd, "log", "기준 1", "echo 기대=3 실제=3")
        self.assertEqual(r.returncode, 0, r.stderr)
        show = job(self.cwd, "show").stdout
        self.assertIn("기준 1", show)
        log = [line for line in show.splitlines() if line.strip().endswith(".log")]
        self.assertTrue(log, show)

    def test_check_는_빠진_것을_모두_알린다(self):
        self.start()
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        for word in ("테스트", "증거", "써 보기"):
            self.assertIn(word, r.stdout)

    def test_다_채우면_check_가_통과한다(self):
        self.start()
        self.complete()
        r = job(self.cwd, "check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_테스트_장치가_없으면_이유로_대신한다(self):
        self.start()
        self.assertEqual(job(self.cwd, "no-test", "이 레포에는 테스트 실행 장치가 없다").returncode, 0)
        job(self.cwd, "evidence", "기준", self.shot())
        job(self.cwd, "try-na", "화면도 명령도 없는 문서 변경")
        self.assertEqual(job(self.cwd, "check").returncode, 0)

    def test_PR_까지만이면_병합_조건을_채워도_막는다(self):
        self.start("--pr-only")
        self.complete()
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PR 까지만", r.stdout)

    def test_사람이_볼_것이_남으면_막는다(self):
        self.start()
        self.complete()
        job(self.cwd, "human", "macOS 앱 화면은 사람이 확인한다")
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("사람이 볼 것", r.stdout)

    def test_사람이_볼_것이_있으면_써_보기를_채운_것으로_친다(self):
        self.start()
        job(self.cwd, "no-test", "장치 없음")
        job(self.cwd, "evidence", "기준", self.shot())
        job(self.cwd, "human", "앱 화면은 사람이 본다")
        out = job(self.cwd, "check").stdout
        self.assertNotIn("직접 써 보기", out)
        self.assertIn("사람이 볼 것", out)

    def test_red_를_다시_돌려도_앞_기록이_남는다(self):
        self.start()
        job(self.cwd, "red", "test -f a.txt")
        job(self.cwd, "red", "test -f b.txt")
        out = job(self.cwd, "show").stdout
        self.assertIn("test -f a.txt", out)
        self.assertIn("test -f b.txt", out)

    def test_커밋_전_변경이_있으면_표시한다(self):
        self.start()
        open(os.path.join(self.cwd, "wip.txt"), "w").close()
        job(self.cwd, "red", "test -f done.txt")
        self.assertIn("커밋 전 변경", job(self.cwd, "show").stdout)

    def test_drop_은_그_기준의_증거를_지운다(self):
        self.start()
        job(self.cwd, "evidence", "기준 A", self.shot("a.png"))
        job(self.cwd, "evidence", "기준 B", self.shot("b.png"))
        self.assertEqual(job(self.cwd, "drop", "기준 A").returncode, 0)
        out = job(self.cwd, "show").stdout
        self.assertNotIn("기준 A", out)
        self.assertIn("기준 B", out)

    def test_log_는_출력을_자르지_않고_따로_번호를_매긴다(self):
        self.start()
        job(self.cwd, "evidence", "기준 A", self.shot())
        job(self.cwd, "log", "기준 B", "seq 1 60")
        path = [line.strip()[2:] for line in job(self.cwd, "show").stdout.splitlines() if line.strip().endswith(".log")][0]
        self.assertTrue(path.endswith("01.log"), path)
        text = open(path, encoding="utf-8").read()
        self.assertIn("\n1\n", text)
        self.assertIn("\n60\n", text)

    def test_show_는_홈_경로를_물결표로_줄인다(self):
        home = os.path.join(self.cwd, "home")
        os.makedirs(home)
        shot = os.path.join(home, "s.png")
        open(shot, "w").close()
        self.start()
        job(self.cwd, "evidence", "기준", shot)
        r = subprocess.run([sys.executable, JOB, "show"], cwd=self.cwd, capture_output=True, text=True,
                           env=dict(os.environ, HOME=home))
        self.assertIn("~/s.png", r.stdout)
        self.assertNotIn(home, r.stdout)

    def test_증거마다_찍은_커밋을_적는다(self):
        self.start()
        job(self.cwd, "evidence", "기준", self.shot())
        self.assertIn("(커밋 없음", job(self.cwd, "show").stdout)

    def test_show_full_은_로그_내용을_붙인다(self):
        self.start()
        job(self.cwd, "log", "기준", "echo 실제=$((1+2))")
        self.assertNotIn("실제=3", job(self.cwd, "show").stdout)
        self.assertIn("실제=3", job(self.cwd, "show", "--full").stdout)

    def test_show_는_PR_본문에_붙일_기록을_낸다(self):
        self.start()
        self.complete()
        job(self.cwd, "pr", "https://github.com/o/r/pull/7")
        job(self.cwd, "merged", "abc1234", "base CI 통과")
        out = job(self.cwd, "show").stdout
        for word in ("test -f done.txt", "기준 1", "화면에서 눌러 봄", "pull/7", "abc1234"):
            self.assertIn(word, out)


if __name__ == "__main__":
    unittest.main()
