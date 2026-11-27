"""고친 뒤 다시 하는 범위: 경로를 적은 증거와 써 보기, 고친 부분만 보는 리뷰, 리뷰 크기, show 의 짧은 출력."""
import json
import os
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
        self.out = tempfile.TemporaryDirectory()  # 스크린샷 같은 증거 파일은 레포 밖에 둔다
        self.addCleanup(self.out.cleanup)
        commit_and_switch(self.cwd, "feat/x")
        commit_file(self.cwd, "src/a.py", "a = 1\n")
        commit_file(self.cwd, "src/b.py", "b = 1\n")
        self.assertEqual(job(self.cwd, "start", "작업").returncode, 0)

    def shot(self, name="shot.png"):
        path = os.path.join(self.out.name, name)
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
            self.assertIn("job.py tried", r.stderr)
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


class ReviewFilesTest(Base):
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

    def test_199줄이면_버그_축만_돌린다(self):
        commit_file(self.cwd, "src/big.py", lines(199))
        out, _ = self.review_files()
        first = out.splitlines()[0]
        self.assertIn("= 199줄", first)
        self.assertIn("버그 축만", first)
        self.assertNotIn("명세 리뷰어를 띄운다", first)

    def test_200줄이면_명세_리뷰어를_띄운다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        first = self.review_files()[0].splitlines()[0]
        self.assertIn("= 200줄", first)
        self.assertIn("명세 리뷰어를 띄운다", first)

    def test_더한_줄과_뺀_줄을_합쳐_센다(self):
        commit_file(self.cwd, "src/big.py", lines(100))
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.cwd, capture_output=True,
                                   text=True).stdout.strip()
        commit_file(self.cwd, "src/big.py", lines(99, "바꾼"))  # 100줄 빼고 99줄 더함
        first = self.review_files()[0].splitlines()[0]
        self.assertIn("더한 줄 99 + 뺀 줄 100 = 199줄", first)
        commit_file(self.cwd, "src/one.py", "x = 1\n")
        self.assertIn("더한 줄 100 + 뺀 줄 100 = 200줄", self.review_files()[0].splitlines()[0])

    def test_첫_리뷰는_base_와의_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        out, diff = self.review_files()
        self.assertIn("전체", out)
        self.assertIn("+줄 0", diff)
        self.assertIn("+줄 199", diff)

    def test_두_번째_리뷰는_앞_리뷰_뒤에_고친_부분만_준다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        self.review_files()
        job(self.cwd, "review", "1", "막는 지적 하나")
        commit_file(self.cwd, "src/fix.py", "고친 줄\n")
        out, diff = self.review_files()
        self.assertIn("고친 부분", out)
        self.assertIn("+고친 줄", diff)
        self.assertNotIn("+줄 0", diff)
        self.assertIn("= 201줄", out.splitlines()[0])  # 줄 수는 늘 base 와의 전체로 센다

    def test_앞_리뷰_커밋이_사라지면_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        self.review_files()
        job(self.cwd, "review", "0")
        self.amend()
        out, diff = self.review_files()
        self.assertIn("전체", out)
        self.assertIn("+줄 0", diff)

    def test_앞_리뷰에서_명세_축이_돌지_않았으면_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(150))
        self.review_files()  # 150줄: 버그 축만
        job(self.cwd, "review", "0")
        commit_file(self.cwd, "src/more.py", lines(80))  # 230줄로 넘는다
        out, diff = self.review_files()
        self.assertIn("명세 리뷰어를 띄운다", out.splitlines()[0])
        self.assertIn("전체", out)
        self.assertIn("+줄 0", diff)

    def test_리뷰_입력을_만들지_않고_남긴_리뷰_뒤에는_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        job(self.cwd, "review", "0")  # review-files 없이: 명세 리뷰어가 이 커밋을 본 적이 없다
        commit_file(self.cwd, "src/fix.py", "고친 줄\n")
        out, diff = self.review_files()
        self.assertIn("전체", out)
        self.assertIn("+줄 0", diff)

    def test_리뷰_입력을_만든_뒤_커밋이_바뀌고_남긴_리뷰_뒤에는_전체를_준다(self):
        commit_file(self.cwd, "src/big.py", lines(200))
        self.review_files()
        commit_file(self.cwd, "src/late.py", "늦게 더한 줄\n")  # 리뷰어가 보지 못한 커밋
        job(self.cwd, "review", "0")
        commit_file(self.cwd, "src/fix.py", "고친 줄\n")
        _, diff = self.review_files()
        self.assertIn("+늦게 더한 줄", diff)
        self.assertIn("+줄 0", diff)


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

    def test_기록하는_명령은_짧은_출력을_낸다(self):
        r = job(self.cwd, "log", "기준 1", "echo 경우=A")
        self.assertNotIn(".log", r.stdout.split("상태:")[1])


class RepoTest(unittest.TestCase):
    def test_파이썬_캐시_폴더는_git_이_무시한다(self):
        for path in ("hooks/__pycache__/job.cpython-312.pyc", "skills/job/__pycache__/job.cpython-312.pyc",
                     "tests/__pycache__/helpers.cpython-312.pyc"):
            r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
            self.assertEqual(r.returncode, 0, path)


if __name__ == "__main__":
    unittest.main()
