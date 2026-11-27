import os
import re
import subprocess
import sys
import tempfile
import unittest

from helpers import JOB, commit_and_switch, git_repo, job, mistakes


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

    def complete(self, door=True):
        """병합 조건을 모두 채운다: red, green, 증거, 써 보기, 리뷰, 되돌릴 수 있는가."""
        self.assertEqual(job(self.cwd, "red", "test -f done.txt").returncode, 0)
        open(os.path.join(self.cwd, "done.txt"), "w").close()
        self.assertEqual(job(self.cwd, "green").returncode, 0)
        self.assertEqual(job(self.cwd, "evidence", "기준 1", self.shot()).returncode, 0)
        self.assertEqual(job(self.cwd, "tried", "화면에서 눌러 봄", self.shot("try.png")).returncode, 0)
        self.assertEqual(job(self.cwd, "review", "0", "작은 변경이라 버그 축만").returncode, 0)
        if door:
            self.assertEqual(job(self.cwd, "door", "two-way", "스크립트 변경, revert 하면 돌아간다").returncode, 0)

    def commit(self):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
                        "--allow-empty", "-m", "수정"], cwd=self.cwd, check=True)

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
        show = job(self.cwd, "show", "--full").stdout
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
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")
        job(self.cwd, "door", "two-way", "문서만 바뀐다")
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

    def test_리뷰_지적이_남으면_막는다(self):
        self.start()
        self.complete()
        job(self.cwd, "review", "2", "널 처리 두 군데")
        out = job(self.cwd, "check").stdout
        self.assertIn("리뷰", out)
        self.assertIn("2", out)

    def test_리뷰가_없으면_막는다(self):
        self.start()
        job(self.cwd, "no-test", "장치 없음")
        job(self.cwd, "evidence", "기준", self.shot())
        job(self.cwd, "try-na", "써 볼 것 없음")
        self.assertIn("리뷰", job(self.cwd, "check").stdout)

    def test_고친_커밋이_생기면_앞_기록을_다시_해야_한다(self):
        self.start()
        self.complete()
        self.assertEqual(job(self.cwd, "check").returncode, 0)
        self.commit()
        out = job(self.cwd, "check").stdout
        for word in ("green", "기준 1", "써 보기", "리뷰"):
            self.assertIn(word, out)

    def test_마지막_커밋에서_다시_하면_통과한다(self):
        self.start()
        self.complete()
        self.commit()
        self.assertEqual(job(self.cwd, "green").returncode, 0)
        job(self.cwd, "evidence", "기준 1", self.shot())
        job(self.cwd, "tried", "화면에서 눌러 봄", self.shot("try.png"))
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")
        r = job(self.cwd, "check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_기준마다_마지막_커밋의_증거가_있어야_한다(self):
        self.start()
        self.complete()
        job(self.cwd, "evidence", "기준 2", self.shot("b.png"))
        self.commit()
        job(self.cwd, "green")
        job(self.cwd, "evidence", "기준 1", self.shot())
        job(self.cwd, "tried", "화면에서 눌러 봄", self.shot("try.png"))
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")
        out = job(self.cwd, "check").stdout
        self.assertIn("기준 2", out)
        self.assertNotIn("기준 1", out)

    def test_stop_은_멈춘_이유를_남기고_병합을_막는다(self):
        self.start()
        self.complete()
        self.assertEqual(job(self.cwd, "stop", "요청대로는 API 가 없어 만들 수 없다").returncode, 0)
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("API 가 없어", r.stdout)
        self.assertIn("API 가 없어", job(self.cwd, "show").stdout)

    def test_scope_로_범위를_바꾼다(self):
        self.start("--pr-only")
        self.complete()
        self.assertIn("PR 까지만", job(self.cwd, "check").stdout)
        self.assertEqual(job(self.cwd, "scope", "merge").returncode, 0)
        self.assertEqual(job(self.cwd, "check").returncode, 0)
        self.assertNotEqual(job(self.cwd, "scope", "deploy").returncode, 0)

    def test_사람_없는_작업으로_시작할_수_있다(self):
        self.start("--unattended")
        self.assertIn("사람 없음", job(self.cwd, "show").stdout)

    def started(self, *args):
        """start 를 돌려 (작업 줄의 제목, 사람 없음인가, PR 까지인가)를 돌려준다."""
        r = job(self.cwd, "start", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = job(self.cwd, "show").stdout
        return ([line[len("- 작업: "):] for line in out.splitlines() if line.startswith("- 작업: ")][0],
                "- 사람 없음" in out, "- 범위: PR 까지" in out)

    def test_start_옵션을_제목_뒤에_써도_읽는다(self):
        self.assertEqual(self.started("제목", "--unattended", "--pr-only"), ("제목", True, True))

    def test_start_옵션을_제목_앞에_써도_읽는다(self):
        self.assertEqual(self.started("--unattended", "--pr-only", "제목"), ("제목", True, True))

    def test_start_옵션을_제목_양쪽에_써도_읽는다(self):
        self.assertEqual(self.started("--pr-only", "제목", "--unattended"), ("제목", True, True))

    def test_start_옵션이_없으면_사람_있음에_병합까지다(self):
        self.assertEqual(self.started("제목"), ("제목", False, False))

    def test_start_는_옵션으로_시작하는_글을_제목으로_받는다(self):
        self.assertEqual(self.started("--unattended 를 앞에서도 읽는다")[0], "--unattended 를 앞에서도 읽는다")

    def test_start_는_모르는_옵션을_제목으로_삼지_않고_사용법을_낸다(self):
        for args in (("--unatended", "제목"), ("제목", "--unatended"), ("--unatended",)):
            r = job(self.cwd, "start", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("모르는 옵션: --unatended", r.stderr)
            self.assertIn("job.py start <제목> [--pr-only] [--unattended]", r.stderr)
            self.assertIn("작업 기록이 없다", job(self.cwd, "show").stderr)  # 시작되지 않았다

    def test_start_는_대문자나_밑줄이_든_모르는_옵션도_제목으로_삼지_않는다(self):
        for option in ("--Unattended", "--pr_only", "--unattended=1"):
            r = job(self.cwd, "start", option)
            self.assertNotEqual(r.returncode, 0, option)
            self.assertIn("모르는 옵션: " + option, r.stderr)
            self.assertIn("작업 기록이 없다", job(self.cwd, "show").stderr)

    def test_증거와_써_보기는_paths_가_아닌_옵션을_받지_않는다(self):
        self.start()
        for args in (("log", "기준", "true", "--path", "x"), ("evidence", "기준", self.shot(), "--path", "x"),
                     ("tried", "써 봄", self.shot(), "--path", "x")):
            r = job(self.cwd, *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("모르는 옵션: --path", r.stderr)
        out = job(self.cwd, "check").stdout
        self.assertIn("증거: 완료 기준에 붙인 로그나 스크린샷이 없다", out)
        self.assertIn("직접 써 보기: 기록이 없다", out)

    def test_drop_은_기준과_tried_를_함께_받지_않는다(self):
        self.start()
        job(self.cwd, "evidence", "기준", self.shot())
        r = job(self.cwd, "drop", "기준", "--tried")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("job.py drop", r.stderr)
        self.assertIn("- 증거:", job(self.cwd, "show").stdout)  # 지워지지 않았다

    def test_start_는_제목이_없거나_둘이면_사용법을_낸다(self):
        for args in ((), ("--unattended",), ("--unattended", "--pr-only"), ("제목", "하나 더"), ("",)):
            r = job(self.cwd, "start", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("job.py start <제목> [--pr-only] [--unattended]", r.stderr)
            self.assertIn("작업 기록이 없다", job(self.cwd, "show").stderr)

    def test_show_와_review_도_모르는_옵션을_받지_않는다(self):
        self.start()
        r = job(self.cwd, "show", "--ful")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("모르는 옵션: --ful", r.stderr)
        self.assertEqual(job(self.cwd, "show", "--full").returncode, 0)
        r = job(self.cwd, "review", "0", "--mino")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("모르는 옵션: --mino", r.stderr)
        self.assertNotIn("- 리뷰(", job(self.cwd, "show").stdout)  # 기록되지 않았다

    def test_모든_명령이_모르는_옵션을_앞뒤_어디서든_받지_않고_아무것도_하지_않는다(self):
        doc = job(self.cwd).stderr  # 인자 없이 돌리면 사용법 전체를 낸다
        commands = list(dict.fromkeys(re.findall(r"^  job\.py (\S+)", doc, re.M)))
        self.assertGreaterEqual(len(commands), 20, doc)
        for name in ("merged", "green", "stop", "mark", "review-files", "check", "door", "pr"):
            self.assertIn(name, commands)
        self.start()
        runs = os.path.join(self.cwd, "runs.txt")
        self.assertEqual(job(self.cwd, "red", "echo 돌았다 >> runs.txt; exit 1").returncode, 0)
        before, state = len(mistakes()), self.state_bytes()
        for cmd in commands:
            for args in ((cmd, "1", "key", "값", "--bogus"), (cmd, "--bogus", "1", "key", "값")):
                r = job(self.cwd, *args)
                self.assertNotEqual(r.returncode, 0, args)
                self.assertIn("모르는 옵션: --bogus", r.stderr, args)
                self.assertIn("job.py " + cmd + " ", r.stderr + " ", args)  # 그 명령의 사용법
        self.assertEqual(self.state_bytes(), state)  # merged, stop, review 같은 기록이 바뀌지 않았다
        self.assertEqual(len(mistakes()), before)  # stop 이 실수 기록에 줄을 붙이지 않았다
        with open(runs, encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1)  # green 과 log 가 명령을 돌리지 않았다

    def test_대시_두_개_뒤의_인자는_옵션이_아니라_값이다(self):
        r = job(self.cwd, "start", "--unattended", "--", "--pr-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = job(self.cwd, "show").stdout
        self.assertIn("- 작업: --pr-only", out)
        self.assertIn("- 범위: 병합까지", out)  # 값으로 받은 --pr-only 는 범위를 바꾸지 않는다
        self.assertIn("- 사람 없음", out)  # -- 앞의 옵션은 그대로 읽는다
        r = job(self.cwd, "review", "0", "--", "--bogus")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("남은 막는 지적 0개 — --bogus", job(self.cwd, "show").stdout)
        before = len(mistakes())
        r = job(self.cwd, "stop", "--", "--unattended")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("상태: 멈춤(--unattended)", job(self.cwd, "show").stdout)
        self.assertEqual(mistakes()[before]["what"], "--unattended")

    def state_bytes(self):
        git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=self.cwd, capture_output=True,
                                 text=True).stdout.strip()
        with open(os.path.join(git_dir, "fade-job.json"), "rb") as f:
            return f.read()

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

    def tracked_change(self):
        path = os.path.join(self.cwd, "app.txt")
        with open(path, "w") as f:
            f.write("v1")
        subprocess.run(["git", "add", "app.txt"], cwd=self.cwd, check=True)
        self.commit()
        with open(path, "w") as f:
            f.write("v2")

    def test_커밋_전_변경이_있으면_표시한다(self):
        self.start()
        self.tracked_change()
        job(self.cwd, "red", "test -f done.txt")
        self.assertIn("커밋 전 변경", job(self.cwd, "show").stdout)

    def test_추적하지_않는_파일만_있으면_커밋_전_변경으로_치지_않는다(self):
        self.start()
        open(os.path.join(self.cwd, "screenshot.png"), "w").close()
        job(self.cwd, "red", "test -f done.txt")
        self.assertNotIn("커밋 전 변경", job(self.cwd, "show").stdout)

    def test_커밋_전_변경으로_찍은_green_과_리뷰는_병합에_치지_않는다(self):
        self.start()
        self.tracked_change()
        self.complete()
        out = job(self.cwd, "check").stdout
        self.assertIn("green", out)
        self.assertIn("리뷰", out)

    def test_기록은_전체_SHA_로_비교하고_짧게_보여_준다(self):
        self.start()
        self.commit()
        self.complete()
        self.assertEqual(job(self.cwd, "check").returncode, 0)
        full = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True, text=True).stdout.strip()
        out = job(self.cwd, "show").stdout
        self.assertIn(full[:7], out)
        self.assertNotIn(full, out)

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
        path = [line.strip()[2:] for line in job(self.cwd, "show", "--full").stdout.splitlines()
                if line.strip().endswith(".log")][0]
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
        r = subprocess.run([sys.executable, JOB, "show", "--full"], cwd=self.cwd, capture_output=True, text=True,
                           env=dict(os.environ, HOME=home))
        self.assertIn("~/s.png", r.stdout)
        self.assertNotIn(home, r.stdout)

    def test_증거마다_찍은_커밋을_적는다(self):
        self.start()
        job(self.cwd, "evidence", "기준", self.shot())
        self.assertIn("커밋 없음", job(self.cwd, "show").stdout)

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

    # 리뷰 입력 파일

    def test_review_files_는_워크트리_안의_무시되는_폴더에_show_와_diff_를_쓴다(self):
        commit_and_switch(self.cwd, "feat/x")
        path = os.path.join(self.cwd, "app.txt")
        with open(path, "w") as f:
            f.write("새 줄\n")
        subprocess.run(["git", "add", "app.txt"], cwd=self.cwd, check=True)
        self.commit()
        self.start()
        r = job(self.cwd, "review-files", "HEAD~1")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(self.cwd, ".fade-review")
        self.assertIn(folder, r.stdout)
        with open(os.path.join(folder, "show.txt"), encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), "상태: 진행 중")
        with open(os.path.join(folder, "diff.patch"), encoding="utf-8") as f:
            self.assertIn("+새 줄", f.read())
        with open(os.path.join(folder, "plan.md"), "w", encoding="utf-8") as f:  # 부르는 쪽이 파일 도구로 쓴다
            f.write("계획서")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.cwd, capture_output=True, text=True)
        added = subprocess.run(["git", "add", "-A", "-n"], cwd=self.cwd, capture_output=True, text=True)
        self.assertEqual((status.stdout, added.stdout), ("", ""))

    def test_review_files_는_없는_base_를_거부한다(self):
        commit_and_switch(self.cwd, "feat/x")
        self.start()
        self.assertNotEqual(job(self.cwd, "review-files", "없는-브랜치").returncode, 0)
        self.assertNotEqual(job(self.cwd, "review-files").returncode, 0)

    # 되돌릴 수 있는가 (door)

    def test_되돌릴_수_있는가가_없으면_막는다(self):
        self.start()
        self.complete(door=False)
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("되돌릴 수 있는가", r.stdout)

    def test_한쪽_문이면_사용자_결정이_필요해_막는다(self):
        self.start()
        self.complete()
        self.assertEqual(job(self.cwd, "door", "one-way", "users 표의 열을 지우는 마이그레이션").returncode, 0)
        r = job(self.cwd, "check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("한쪽 문", r.stdout)
        self.assertIn("users 표의 열을 지우는 마이그레이션", r.stdout)
        self.assertIn("사용자", r.stdout)

    def test_양쪽_문이면_door_는_막지_않는다(self):
        self.start()
        self.complete()
        self.assertEqual(job(self.cwd, "check").returncode, 0)
        show = job(self.cwd, "show").stdout
        self.assertIn("되돌릴 수 있는가: 양쪽 문", show)
        self.assertIn("revert 하면 돌아간다", show)

    def test_door_는_종류와_이유가_있어야_한다(self):
        self.start()
        self.assertNotEqual(job(self.cwd, "door", "maybe", "이유").returncode, 0)
        self.assertNotEqual(job(self.cwd, "door", "two-way").returncode, 0)
        self.assertNotEqual(job(self.cwd, "door", "two-way", "  ").returncode, 0)

    # show 첫 줄의 상태

    def first_line(self):
        return job(self.cwd, "show").stdout.splitlines()[0]

    def test_show_첫_줄은_진행_중_상태다(self):
        self.start()
        self.assertEqual(self.first_line(), "상태: 진행 중")

    def test_show_첫_줄은_멈춘_이유를_보인다(self):
        self.start()
        job(self.cwd, "stop", "권한 설정이 push 를 막았다")
        self.assertEqual(self.first_line(), "상태: 멈춤(권한 설정이 push 를 막았다)")

    def test_show_첫_줄은_PR_까지인_작업의_PR_이_열리면_PR_까지다(self):
        self.start("--pr-only")
        self.assertEqual(self.first_line(), "상태: 진행 중")
        job(self.cwd, "pr", "https://github.com/o/r/pull/7")
        self.assertEqual(self.first_line(), "상태: PR 까지")

    def test_show_첫_줄은_병합되면_병합됨이다(self):
        self.start()
        job(self.cwd, "stop", "한쪽 문이라 사용자가 정한다")
        job(self.cwd, "merged", "abc1234")
        self.assertEqual(self.first_line(), "상태: 병합됨")

    def test_병합_조건을_채워도_병합_전이면_진행_중이다(self):
        self.start()
        self.complete()
        job(self.cwd, "pr", "https://github.com/o/r/pull/7")
        self.assertEqual(self.first_line(), "상태: 진행 중")

    # 실수 기록

    def own_log(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "없는 폴더", "mistakes.jsonl")
        return path, dict(os.environ, FADE_MISTAKES=path)

    def test_stop_은_실수_기록에_한_줄_남긴다(self):
        path, env = self.own_log()
        commit_and_switch(self.cwd, "feat/x")
        self.start()
        job(self.cwd, "pr", "https://github.com/o/r/pull/7")
        self.assertEqual(job(self.cwd, "stop", "같은 실패를 두 번 고쳐도 남는다", env=env).returncode, 0)
        rows = mistakes(path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source"], "stop")
        self.assertEqual(row["what"], "같은 실패를 두 번 고쳐도 남는다")
        self.assertEqual(row["pr"], "https://github.com/o/r/pull/7")
        self.assertEqual(row["branch"], "feat/x")
        self.assertEqual(os.path.realpath(row["repo"]), os.path.realpath(self.cwd))
        self.assertEqual((row["key"], row["handled"]), ("", ""))
        self.assertRegex(row["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertIn("멈춤", job(self.cwd, "show").stdout)  # 기록과 함께 상태도 남는다

    def test_slip_은_리뷰_CI_사용자_지적을_남긴다(self):
        path, env = self.own_log()
        self.start()
        for source, what in (("review", "빈 목록에서 첫 원소를 읽었다"), ("ci", "3.12 에 없는 문법을 썼다"),
                             ("user", "PR 본문에 #3 을 썼다")):
            r = job(self.cwd, "slip", source, what, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([(m["source"], m["what"]) for m in mistakes(path)],
                         [("review", "빈 목록에서 첫 원소를 읽었다"), ("ci", "3.12 에 없는 문법을 썼다"),
                          ("user", "PR 본문에 #3 을 썼다")])

    def test_slip_은_훅이_직접_쓰는_출처와_빈_내용을_받지_않는다(self):
        path, env = self.own_log()
        self.start()
        for args in (("gate", "x"), ("permission", "x"), ("stop", "x"), ("deploy", "x"), ("review",), ("review", " ")):
            self.assertNotEqual(job(self.cwd, "slip", *args, env=env).returncode, 0, args)
        self.assertEqual(mistakes(path), [])

    def test_실수_기록의_레포는_워크트리가_아니라_메인_체크아웃이다(self):
        path, env = self.own_log()
        commit_and_switch(self.cwd, "base")
        wt = os.path.join(self.cwd, "wt")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "feat/x", wt], cwd=self.cwd, check=True)
        self.assertEqual(job(wt, "start", "작업").returncode, 0)
        self.assertEqual(job(wt, "slip", "user", "지적", env=env).returncode, 0)
        row = mistakes(path)[0]
        self.assertEqual(os.path.realpath(row["repo"]), os.path.realpath(self.cwd))
        self.assertEqual(row["branch"], "feat/x")

    def test_mark_는_그_줄의_key_와_처리만_바꾼다(self):
        path, env = self.own_log()
        self.start()
        job(self.cwd, "slip", "ci", "CI 가 끝나기 전에 병합했다", env=env)
        job(self.cwd, "slip", "user", "브랜치 이름 규칙을 어겼다", env=env)
        outside = tempfile.TemporaryDirectory()  # git 레포가 아닌 곳(리드의 상위 폴더)에서도 돈다
        self.addCleanup(outside.cleanup)
        r = job(outside.name, "mark", "2", "key", "branch-name", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(job(outside.name, "mark", "2", "handled", "처리됨(사용자 settings 의 브랜치 이름 훅)",
                             env=env).returncode, 0)
        first, second = mistakes(path)
        self.assertEqual((first["key"], first["handled"]), ("", ""))
        self.assertEqual((second["key"], second["handled"]), ("branch-name", "처리됨(사용자 settings 의 브랜치 이름 훅)"))
        self.assertEqual(second["what"], "브랜치 이름 규칙을 어겼다")

    def test_mark_는_없는_줄과_없는_칸을_거부한다(self):
        path, env = self.own_log()
        self.start()
        job(self.cwd, "slip", "user", "지적", env=env)
        for args in (("3", "key", "x"), ("0", "key", "x"), ("일", "key", "x"), ("1", "what", "바꿈"), ("1", "key")):
            self.assertNotEqual(job(self.cwd, "mark", *args, env=env).returncode, 0, args)
        self.assertEqual(mistakes(path)[0]["what"], "지적")


if __name__ == "__main__":
    unittest.main()
