import os
import unittest

from helpers import commit_and_switch, git_repo, job


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
