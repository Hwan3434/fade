"""고친 뒤 다시 하는 범위: 경로를 적은 증거와 써 보기, 고친 부분만 보는 리뷰, 리뷰 크기, show 의 짧은 출력."""
import json
import os
import re
import subprocess
import tempfile
import unittest

from helpers import ROOT, commit_and_switch, commit_file, git_repo, job

GIT = ["git", "-c", "user.name=fade-test", "-c", "user.email=fade-test@example.invalid"]


def lines(n, word="줄"):
    return "".join("%s %d\n" % (word, i) for i in range(n))


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        self.out = tempfile.TemporaryDirectory()  # 레포 밖의 폴더
        self.addCleanup(self.out.cleanup)
        commit_and_switch(self.cwd, "feat/x")
        commit_file(self.cwd, "src/a.py", "a = 1\n")
        commit_file(self.cwd, "src/b.py", "b = 1\n")
        self.assertEqual(job(self.cwd, "start", "작업").returncode, 0)

    def shot(self, name="shot.png"):
        # 증거 파일은 tester 가 남기는 자리(git 폴더 안 fade-try/)에 둔다. 레포 밖 임시 폴더의 파일은 받지 않는다
        folder = os.path.join(subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=self.cwd,
                                             capture_output=True, text=True).stdout.strip(), "fade-try")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        open(path, "w").close()
        return path

    def check(self):
        return job(self.cwd, "check").stdout

    def state(self):
        git_dir = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=self.cwd, capture_output=True,
                                 text=True).stdout.strip()
        return os.path.join(git_dir, "fade-job.json")

    def amend(self):
        subprocess.run(GIT + ["commit", "-q", "--amend", "--allow-empty", "-m", "다시 쓴 커밋"], cwd=self.cwd, check=True)


class EvidencePathsTest(Base):
    def test_경로가_안_바뀌면_앞_커밋의_증거가_유효하다(self):
        r = job(self.cwd, "log", "기준 1", "echo 실제=1", "--paths", "src/a.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        commit_file(self.cwd, "src/b.py", "b = 2\n")
        self.assertNotIn("기준 1", self.check())

    def test_경로가_바뀌면_증거가_무효다(self):
        job(self.cwd, "log", "기준 1", "echo 실제=1", "--paths", "src/a.py")
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        self.assertIn("기준 1", self.check())

    def test_폴더를_경로로_적으면_그_안의_변경을_본다(self):
        job(self.cwd, "evidence", "기준 1", self.shot(), "--paths", "src")
        commit_file(self.cwd, "docs/x.md", "글\n")
        self.assertNotIn("기준 1", self.check())
        commit_file(self.cwd, "src/c.py", "c = 1\n")
        self.assertIn("기준 1", self.check())

    def test_경로를_적지_않은_증거는_지금_커밋의_것만_친다(self):
        job(self.cwd, "log", "기준 1", "echo 실제=1")
        self.assertNotIn("기준 1", self.check())
        commit_file(self.cwd, "docs/x.md", "글\n")
        self.assertIn("기준 1", self.check())

    def test_찍은_커밋이_사라지면_무효다(self):
        job(self.cwd, "log", "기준 1", "echo 실제=1", "--paths", "src/a.py")
        self.amend()  # 경로 내용은 그대로지만 찍은 커밋이 지금 커밋의 조상이 아니다
        self.assertIn("기준 1", self.check())

    def test_찍은_커밋이_없는_SHA_면_무효다(self):
        job(self.cwd, "log", "기준 1", "echo 실제=1", "--paths", "src/a.py")
        with open(self.state(), encoding="utf-8") as f:
            state = json.load(f)
        state["evidence"][0]["head"] = "0123456789abcdef0123456789abcdef01234567"
        with open(self.state(), "w", encoding="utf-8") as f:
            json.dump(state, f)
        self.assertIn("기준 1", self.check())

    def test_같은_기준의_유효한_증거가_낡은_증거를_가리지_않는다(self):
        job(self.cwd, "log", "기준 1", "echo 경우=A", "--paths", "src/a.py")
        job(self.cwd, "log", "기준 1", "echo 경우=B", "--paths", "src/b.py")
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        out = self.check()
        self.assertIn("기준 1", out)
        self.assertIn("echo 경우=A", out)  # 무엇을 다시 남길지 알린다
        self.assertNotIn("echo 경우=B", out)

    def test_같은_명령으로_다시_남기면_낡은_증거를_바꾼다(self):
        job(self.cwd, "log", "기준 1", "echo 경우=A", "--paths", "src/a.py")
        job(self.cwd, "log", "기준 1", "echo 경우=B", "--paths", "src/b.py")
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        job(self.cwd, "log", "기준 1", "echo 경우=A", "--paths", "src/a.py")
        self.assertNotIn("기준 1", self.check())
        with open(self.state(), encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["evidence"]), 2)

    def test_같은_파일로_다시_붙이면_낡은_증거를_바꾼다(self):
        job(self.cwd, "evidence", "기준 1", self.shot())
        commit_file(self.cwd, "docs/x.md", "글\n")
        job(self.cwd, "evidence", "기준 1", self.shot())
        self.assertNotIn("기준 1", self.check())

    def test_없는_경로는_거부한다(self):
        r = job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src/오타.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("src/오타.py", r.stderr)
        self.assertIn("증거: 완료 기준에 붙인", self.check())  # 기록되지 않았다

    def test_경로_없이_paths_만_주면_거부한다(self):
        self.assertNotEqual(job(self.cwd, "log", "기준 1", "echo 1", "--paths").returncode, 0)

    def test_paths_앞에_아무것도_없으면_사용법을_낸다(self):
        for cmd in ("tried", "evidence", "log"):
            r = job(self.cwd, cmd, "--paths", "src/a.py")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("job.py %s <" % cmd, r.stderr)  # 그 명령의 사용법
            self.assertNotIn("Traceback", r.stderr)

    def test_명령이_기대는_경로를_고치면_기록하지_않는다(self):
        r = job(self.cwd, "log", "기준 1", "echo 'a = 9' > src/a.py", "--paths", "src/a.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("증거: 완료 기준에 붙인", self.check())

    def test_점_둘로_시작하는_레포_안_이름은_받는다(self):
        commit_file(self.cwd, "..data/x.json", "{}\n")
        self.assertEqual(job(self.cwd, "log", "기준 1", "echo 1", "--paths", "..data").returncode, 0)

    def test_여러_줄_명령도_낡은_증거_이름은_한_줄이다(self):
        job(self.cwd, "log", "기준 1", "echo 첫째\necho 둘째")
        commit_file(self.cwd, "docs/x.md", "글\n")
        line = [x for x in self.check().splitlines() if "기준 1" in x]
        self.assertEqual(len(line), 1)
        self.assertIn("echo 첫째 echo 둘째", line[0])

    def test_링크를_경로로_적으면_링크가_가리키는_곳이_바뀌는_것도_본다(self):
        os.symlink("a.py", os.path.join(self.cwd, "src", "link.py"))
        subprocess.run(["git", "add", "src/link.py"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "링크"], cwd=self.cwd, check=True)
        self.assertEqual(job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src/link.py").returncode, 0)
        os.remove(os.path.join(self.cwd, "src", "link.py"))
        os.symlink("b.py", os.path.join(self.cwd, "src", "link.py"))
        subprocess.run(["git", "add", "src/link.py"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "링크를 바꿈"], cwd=self.cwd, check=True)
        self.assertIn("「기준 1」의 낡은 증거", self.check())

    def test_링크를_경로로_적으면_링크가_가리키는_파일의_내용이_바뀌는_것도_본다(self):
        os.symlink("a.py", os.path.join(self.cwd, "src", "link.py"))
        subprocess.run(["git", "add", "src/link.py"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "링크"], cwd=self.cwd, check=True)
        job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src/link.py")
        commit_file(self.cwd, "src/b.py", "b = 2\n")
        self.assertNotIn("기준 1", self.check())
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        self.assertIn("「기준 1」의 낡은 증거", self.check())

    def test_추적하지_않는_파일을_숨기는_git_설정에서도_경로의_새_파일을_본다(self):
        subprocess.run(["git", "config", "status.showUntrackedFiles", "no"], cwd=self.cwd, check=True)
        open(os.path.join(self.cwd, "src", "new.py"), "w").close()
        r = job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("추적하지 않는 파일", r.stderr)
        self.assertIn("src/new.py", r.stderr)

    def test_링크가_가리키는_파일을_추적하지_않으면_그_자리를_알린다(self):
        open(os.path.join(self.cwd, "tmp.py"), "w").close()
        os.symlink("../tmp.py", os.path.join(self.cwd, "src", "link.py"))
        subprocess.run(["git", "add", "src/link.py"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "링크"], cwd=self.cwd, check=True)
        r = job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src/link.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("링크가 가리키는 tmp.py", r.stderr)

    def test_커밋을_모르는_옛_기록이_있어도_show_가_죽지_않는다(self):
        job(self.cwd, "log", "기준 1", "echo 1")
        job(self.cwd, "tried", "써 봄", self.shot())
        with open(self.state(), encoding="utf-8") as f:
            state = json.load(f)
        del state["evidence"][0]["head"], state["tried"][0]["head"]
        with open(self.state(), "w", encoding="utf-8") as f:
            json.dump(state, f)
        r = job(self.cwd, "show")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("기준 1", r.stdout)

    def test_절대_경로로_적어도_레포_기준으로_남는다(self):
        r = job(self.cwd, "log", "기준 1", "echo 1", "--paths", os.path.join(self.cwd, "src", "a.py"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("기대는 경로 src/a.py", job(self.cwd, "show", "--full").stdout)

    def test_레포_밖_경로는_거부한다(self):
        self.assertNotEqual(job(self.cwd, "log", "기준 1", "echo 1", "--paths", self.out.name).returncode, 0)

    def test_추적하는_파일이_없는_경로는_거부한다(self):
        os.makedirs(os.path.join(self.cwd, "build"))
        with open(os.path.join(self.cwd, ".gitignore"), "w") as f:
            f.write("build/\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=self.cwd, check=True)
        subprocess.run(GIT + ["commit", "-q", "-m", "무시"], cwd=self.cwd, check=True)
        open(os.path.join(self.cwd, "build", "out.bin"), "w").close()
        self.assertNotEqual(job(self.cwd, "log", "기준 1", "echo 1", "--paths", "build").returncode, 0)

    def test_경로에_커밋_전_변경이_있으면_거부한다(self):
        with open(os.path.join(self.cwd, "src", "a.py"), "w") as f:
            f.write("a = 9\n")
        r = job(self.cwd, "log", "기준 1", "echo 1", "--paths", "src/a.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("커밋", r.stderr)

    def test_경로에_추적하지_않는_파일이_있으면_거부한다(self):
        open(os.path.join(self.cwd, "src", "new.py"), "w").close()
        self.assertNotEqual(job(self.cwd, "evidence", "기준 1", self.shot(), "--paths", "src").returncode, 0)

    def test_하위_폴더에서_돌려도_경로는_레포_기준으로_남는다(self):
        r = job(os.path.join(self.cwd, "src"), "log", "기준 1", "echo 1", "--paths", "a.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        self.assertIn("기준 1", self.check())


class TriedPathsTest(Base):
    def test_경로가_안_바뀌면_앞_커밋의_써_보기가_유효하다(self):
        job(self.cwd, "tried", "명령으로 써 봄", self.shot(), "--paths", "src/a.py")
        commit_file(self.cwd, "src/b.py", "b = 2\n")
        self.assertNotIn("직접 써 보기", self.check())

    def test_경로가_바뀌면_써_보기가_무효다(self):
        job(self.cwd, "tried", "명령으로 써 봄", self.shot(), "--paths", "src/a.py")
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        self.assertIn("직접 써 보기: 낡은 기록", self.check())

    def test_경로를_적지_않은_써_보기는_지금_커밋의_것만_친다(self):
        job(self.cwd, "tried", "명령으로 써 봄", self.shot())
        self.assertNotIn("직접 써 보기", self.check())
        commit_file(self.cwd, "docs/x.md", "글\n")
        self.assertIn("직접 써 보기: 낡은 기록", self.check())

    def test_찍은_커밋이_사라지면_써_보기가_무효다(self):
        job(self.cwd, "tried", "명령으로 써 봄", self.shot(), "--paths", "src/a.py")
        self.amend()
        self.assertIn("직접 써 보기: 낡은 기록", self.check())

    def test_유효한_써_보기가_낡은_써_보기를_가리지_않는다(self):
        job(self.cwd, "tried", "A 화면", self.shot("a.png"), "--paths", "src/a.py")
        job(self.cwd, "tried", "B 화면", self.shot("b.png"), "--paths", "src/b.py")
        commit_file(self.cwd, "src/a.py", "a = 2\n")
        out = self.check()
        self.assertIn("A 화면", out)
        self.assertNotIn("B 화면", out)
        job(self.cwd, "tried", "A 화면", self.shot("a.png"), "--paths", "src/a.py")  # 같은 이름으로 다시 하면 바뀐다
        self.assertNotIn("직접 써 보기", self.check())

    def test_drop_tried_는_써_보기를_모두_지운다(self):
        job(self.cwd, "tried", "옛 방식", self.shot())
        commit_file(self.cwd, "docs/x.md", "글\n")
        self.assertEqual(job(self.cwd, "drop", "--tried").returncode, 0)
        job(self.cwd, "tried", "새 방식", self.shot())
        out = self.check()
        self.assertNotIn("직접 써 보기", out)
        self.assertNotIn("옛 방식", job(self.cwd, "show", "--full").stdout)


class ReviewBase(Base):
    """base 는 src/b.py 를 더한 커밋이다. 그 뒤의 커밋이 이 작업의 변경이다."""

    def setUp(self):
        super().setUp()
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                                   text=True).stdout.strip()

    def review_files(self):
        r = job(self.cwd, "review-files", self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.cwd, ".fade-review", "diff.patch"), encoding="utf-8") as f:
            return r.stdout, f.read()


class ReviewFilesTest(ReviewBase):
    """review-files 는 명세 리뷰어를 띄울지 정하지 않고 판단 재료(줄 수, 파일 수와 목록)만 알린다."""

    def test_작은_변경도_큰_변경도_리뷰_축을_정하지_않고_판단_재료만_알린다(self):
        for n in (3, 900):
            commit_file(self.cwd, "src/big%d.py" % n, lines(n))
            commit_file(self.cwd, "docs/note%d.md" % n, lines(n, "글"))
            out, _ = self.review_files()
            first = out.splitlines()[0]
            self.assertIn("파일 2개", first)
            self.assertIn("더한 줄 %d + 뺀 줄 0 = %d줄" % (2 * n, 2 * n), first)
            self.assertIn("%d\t0\tsrc/big%d.py" % (n, n), out)
            self.assertIn("%d\t0\tdocs/note%d.md" % (n, n), out)
            for word in ("버그 축만", "명세 리뷰어를 띄운다", "미만", "이상"):
                self.assertNotIn(word, out)
            self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                                       text=True).stdout.strip()

    def test_더한_줄과_뺀_줄을_합쳐_센다(self):
        commit_file(self.cwd, "src/big.py", lines(100))
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                                   text=True).stdout.strip()
        commit_file(self.cwd, "src/big.py", lines(99, "바꾼"))  # 100줄 빼고 99줄 더함
        first = self.review_files()[0].splitlines()[0]
        self.assertIn("파일 1개, 더한 줄 99 + 뺀 줄 100 = 199줄", first)

    def test_줄_수_고정_기준이_어디에도_없다(self):
        files = ["skills/job/job.py", "skills/job/stages/review.md", "README.md", "README.en.md", "README.ja.md",
                 "README.zh.md"]
        for name in files:
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("SPEC_REVIEW_LINES", text, name)
            self.assertIsNone(re.search(r"\d+\s*(줄|lines?|行)\s*(이상|미만|or more|以上|未満|及以上)", text), name)

    def test_첫_리뷰는_base_와의_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        out, diff = self.review_files()
        self.assertIn("전체", out.splitlines()[1])
        self.assertIn("+줄 0", diff)
        self.assertIn("+줄 19", diff)

    def test_두_번째_리뷰는_명세_리뷰어가_본_뒤에_고친_부분만_준다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        self.assertEqual(job(self.cwd, "review", "1", "막는 지적 하나", "--spec").returncode, 0)
        commit_file(self.cwd, "src/fix.py", "고친 줄\n")
        out, diff = self.review_files()
        self.assertIn("고친 부분", out.splitlines()[1])
        self.assertIn("+고친 줄", diff)
        self.assertNotIn("+줄 0", diff)
        self.assertIn("= 21줄", out.splitlines()[0])  # 줄 수는 늘 base 와의 전체로 센다

    def test_명세_리뷰어를_띄우지_않은_리뷰는_이유를_요약에_남겨야_받는다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        for args in (("0",), ("0", " ")):
            r = job(self.cwd, "review", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertIn("띄우지 않은 이유", r.stderr)
        self.assertNotIn("- 리뷰(", job(self.cwd, "show").stdout)  # 기록되지 않았다
        r = job(self.cwd, "review", "0", "글만 바꾼 한 파일이라 버그 축만")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = job(self.cwd, "show").stdout
        self.assertIn("— 글만 바꾼 한 파일이라 버그 축만", out)
        self.assertNotIn("명세 리뷰어도 봄", out)

    def test_명세_리뷰어가_본_리뷰는_show_에_나온다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        r = job(self.cwd, "review", "0", "--spec")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("명세 리뷰어도 봄", job(self.cwd, "show").stdout)

    def test_명세_리뷰어를_띄우지_않은_리뷰_뒤에는_명세_리뷰어가_마지막으로_본_뒤의_diff_를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        job(self.cwd, "review", "1", "막는 지적 하나", "--spec")
        commit_file(self.cwd, "src/fix.py", "고친 줄\n")
        self.review_files()
        self.assertEqual(job(self.cwd, "review", "1", "한 줄 수정이라 버그 축만").returncode, 0)
        commit_file(self.cwd, "src/fix2.py", "또 고친 줄\n")
        out, diff = self.review_files()
        self.assertIn("고친 부분", out.splitlines()[1])
        self.assertIn("+고친 줄", diff)  # 명세 리뷰어가 보지 못한 커밋도 담는다
        self.assertIn("+또 고친 줄", diff)
        self.assertNotIn("+줄 0", diff)

    def test_앞_리뷰_커밋이_사라지면_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        job(self.cwd, "review", "0", "--spec")
        self.amend()
        out, diff = self.review_files()
        self.assertIn("전체", out.splitlines()[1])
        self.assertIn("+줄 0", diff)

    def test_명세_리뷰어가_돈_적이_없으면_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        job(self.cwd, "review", "0", "작은 변경이라 버그 축만")
        commit_file(self.cwd, "src/more.py", lines(80))
        out, diff = self.review_files()
        self.assertIn("전체", out.splitlines()[1])
        self.assertIn("+줄 0", diff)

    def test_spec_은_그_커밋에서_만든_리뷰_입력이_있어야_받는다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        r = job(self.cwd, "review", "0", "--spec")  # review-files 없이: 명세 리뷰어가 이 커밋을 본 적이 없다
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("review-files", r.stderr)
        self.review_files()
        commit_file(self.cwd, "src/late.py", "늦게 더한 줄\n")  # 리뷰어가 보지 못한 커밋
        r = job(self.cwd, "review", "0", "--spec")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("review-files", r.stderr)
        self.assertNotIn("- 리뷰(", job(self.cwd, "show").stdout)

    def test_spec_과_minor_를_함께_받지_않는다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        job(self.cwd, "review", "0", "--spec")
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        self.review_files()
        r = job(self.cwd, "review", "0", "--spec", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("함께", r.stderr)


class ShowTest(Base):
    def fill(self):
        job(self.cwd, "log", "기준 1", "echo 경우=A")
        job(self.cwd, "log", "기준 1", "echo 경우=B; exit 3")
        job(self.cwd, "evidence", "기준 2", self.shot("화면.png"))
        job(self.cwd, "tried", "명령으로 써 봄", self.shot("try.png"), "--paths", "src/a.py")

    def test_기본_출력은_기준마다_한_줄이고_명령과_파일_경로가_없다(self):
        self.fill()
        out = job(self.cwd, "show").stdout
        head = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=self.cwd, capture_output=True,
                              text=True).stdout.strip()
        line = [x for x in out.splitlines() if "기준 1" in x]
        self.assertEqual(len(line), 1, out)
        for word in ("증거 2개", "종료 코드 0, 3", "커밋 " + head):
            self.assertIn(word, line[0])
        for word in ("echo 경우", ".log", "화면.png", "try.png", "src/a.py"):
            self.assertNotIn(word, out)
        self.assertIn("기준 2", out)
        self.assertIn("명령으로 써 봄", out)

    def test_full_은_명령_전문과_로그_경로와_기대는_경로를_낸다(self):
        self.fill()
        out = job(self.cwd, "show", "--full").stdout
        for word in ("echo 경우=A", "echo 경우=B; exit 3", "01.log", "02.log", "화면.png", "try.png", "src/a.py"):
            self.assertIn(word, out)

    def test_기본_출력이_full_보다_짧다(self):
        self.fill()
        short = job(self.cwd, "show").stdout.splitlines()
        full = job(self.cwd, "show", "--full").stdout.splitlines()
        self.assertLess(len(short), len(full))
        self.assertEqual(len([x for x in short if x.startswith("  - ")]), 3)  # 기준 둘과 써 보기 하나


class RepoTest(unittest.TestCase):
    def test_파이썬_캐시_폴더는_git_이_무시한다(self):
        for path in ("hooks/__pycache__/job.cpython-312.pyc", "skills/job/__pycache__/job.cpython-312.pyc",
                     "tests/__pycache__/helpers.cpython-312.pyc"):
            r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
            self.assertEqual(r.returncode, 0, path)


class MinorReviewTest(ReviewBase):
    """막는 지적이 0 이 된 뒤 사소한 지적을 한 커밋으로 고치고, 그 커밋만 버그 축으로 본 리뷰(review --minor)."""

    def spec_reviewed(self):
        """변경을 명세 리뷰어까지 보고 막는 지적 0 으로 남긴다."""
        commit_file(self.cwd, "src/big.py", lines(20))
        self.review_files()
        self.assertEqual(job(self.cwd, "review", "0", "사소한 지적 둘", "--spec").returncode, 0)

    def review(self):
        with open(self.state(), encoding="utf-8") as f:
            return json.load(f)["review"]

    def test_사소한_지적이_없으면_앞_리뷰가_그대로_병합_조건을_채운다(self):
        self.spec_reviewed()
        self.assertNotIn("리뷰:", self.check())

    def test_여러_개를_한_커밋으로_고친_뒤의_리뷰는_병합_조건을_채운다(self):
        self.spec_reviewed()
        subprocess.run(GIT + ["commit", "-q", "--allow-empty", "-m", "사소한 지적 둘을 고친다"], cwd=self.cwd, check=True)
        self.assertIn("리뷰: 마지막 커밋", self.check())  # 고친 커밋이 생겨 앞 리뷰는 낡았다
        r = job(self.cwd, "review", "0", "사소한 지적 둘을 고침", "--minor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("리뷰:", self.check())
        out = job(self.cwd, "show").stdout
        self.assertIn("사소한 지적을 모아 고친 커밋", out)
        self.assertIn("— 사소한 지적 둘을 고침", out)
        self.assertEqual(self.review()["note"], "사소한 지적 둘을 고침")

    def test_minor_를_수_앞에_써도_옵션으로_읽는다(self):
        self.spec_reviewed()
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        r = job(self.cwd, "review", "--minor", "0", "요약")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.review()["left"], self.review()["note"]), (0, "요약"))
        self.assertIn("사소한 지적을 모아 고친 커밋", job(self.cwd, "show").stdout)

    def test_그_커밋에서_막는_지적이_나오면_원래_흐름으로_돌아가_명세_리뷰어가_본_뒤의_diff_를_준다(self):
        self.spec_reviewed()
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        self.assertEqual(job(self.cwd, "review", "1", "막는 지적 하나", "--minor").returncode, 0)
        self.assertIn("남은 막는 지적 1개", self.check())
        commit_file(self.cwd, "src/fix.py", "막는 지적 수정\n")
        job(self.cwd, "slip", "review", "k", "막는 지적을 고쳤다")  # 줄어든 막는 지적에는 고친 흔적이 있어야 한다
        out, diff = self.review_files()
        self.assertIn("고친 부분", out)
        self.assertIn("+사소한 수정", diff)  # 명세 리뷰어가 보지 못한 사소한 수정 커밋도 담는다
        self.assertIn("+막는 지적 수정", diff)
        self.assertNotIn("+줄 0", diff)
        self.assertEqual(job(self.cwd, "review", "0", "--spec").returncode, 0)
        self.assertNotIn("리뷰:", self.check())
        self.assertNotIn("사소한 지적을 모아 고친 커밋", job(self.cwd, "show").stdout)

    def test_그_커밋에서_리뷰_입력을_만들었어도_명세_리뷰어가_본_것으로_치지_않는다(self):
        self.spec_reviewed()
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        self.review_files()
        self.assertEqual(job(self.cwd, "review", "1", "--minor").returncode, 0)
        commit_file(self.cwd, "src/fix.py", "막는 지적 수정\n")
        _, diff = self.review_files()
        self.assertIn("+사소한 수정", diff)
        self.assertNotIn("+줄 0", diff)

    def test_앞_리뷰가_없거나_막는_지적이_남았으면_minor_를_받지_않는다(self):
        commit_file(self.cwd, "src/big.py", lines(20))
        r = job(self.cwd, "review", "0", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("막는 지적이 0", r.stderr)
        self.review_files()
        job(self.cwd, "review", "2", "막는 지적 둘", "--spec")
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        r = job(self.cwd, "review", "0", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("막는 지적이 0", r.stderr)
        self.assertIn("커밋 전 변경 없이", r.stderr)
        self.assertEqual(self.review()["left"], 2)  # 거부하면 앞 기록을 바꾸지 않는다

    def test_앞_리뷰_뒤의_커밋이_하나가_아니면_minor_를_받지_않는다(self):
        self.spec_reviewed()
        r = job(self.cwd, "review", "0", "--minor")  # 고친 커밋이 없다
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("0개", r.stderr)
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        commit_file(self.cwd, "src/nit2.py", "사소한 수정 둘\n")
        r = job(self.cwd, "review", "0", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("2개", r.stderr)
        self.assertIn("review-files", r.stderr)

    def test_앞_리뷰_커밋이_사라졌으면_minor_를_받지_않는다(self):
        self.spec_reviewed()
        self.amend()
        r = job(self.cwd, "review", "0", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("review-files", r.stderr)

    def test_사소한_지적을_고친_커밋의_리뷰_뒤에_또_minor_를_받지_않는다(self):
        self.spec_reviewed()
        commit_file(self.cwd, "src/nit.py", "사소한 수정\n")
        self.assertEqual(job(self.cwd, "review", "0", "--minor").returncode, 0)
        commit_file(self.cwd, "src/nit2.py", "사소한 수정 둘\n")
        r = job(self.cwd, "review", "0", "--minor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("한 번에", r.stderr)
        _, diff = self.review_files()  # 원래 흐름으로 가면 명세 리뷰어가 보지 못한 두 커밋을 함께 받는다
        self.assertIn("+사소한 수정\n", diff)
        self.assertIn("+사소한 수정 둘", diff)
        self.assertNotIn("+줄 0", diff)


if __name__ == "__main__":
    unittest.main()
