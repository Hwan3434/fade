"""스킬, 에이전트, 훅의 글이 지켜야 하는 것을 소스에서 본다."""
import os
import re
import subprocess
import unittest

from helpers import ROOT

# 모델은 사람마다 고르는 값이다. fade 의 어디에 박혀도 쓰는 사람의 선택을 덮는다
# 한글은 단어 글자라 「Sonnet으로」에서 \b 가 갈리지 않는다. 앞뒤가 영문자가 아닌지만 본다
MODEL_NAME = re.compile(r"(?<![a-z])(opus|sonnet|haiku|fable)(?![a-z])|claude-[a-z]+-\d", re.I)
MODEL_KEY = re.compile(r"^\s*\"?model\"?\s*:")  # frontmatter 의 model: 과 JSON 의 "model":


def names_model(line):
    return bool(MODEL_KEY.search(line) or MODEL_NAME.search(line))


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def plugin_files():
    tracked = subprocess.run(["git", "ls-files", "agents", "skills", "hooks"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    return [p for p in tracked if os.path.isfile(os.path.join(ROOT, p))]


def section(text, title):
    """`### 정리` 같은 제목 줄부터, 같은 깊이 이하의 다음 제목 전까지."""
    m = re.search(r"^(#+) %s$" % re.escape(title), text, re.M)
    if not m:
        raise AssertionError("절이 없다: " + title)
    end = re.compile(r"^#{1,%d} " % len(m.group(1)), re.M).search(text, m.end())
    return text[m.end():end.start() if end else len(text)]


class ModelNameTest(unittest.TestCase):
    def test_플러그인_파일에_모델_이름이_없다(self):
        found = []
        for rel in plugin_files():
            for n, line in enumerate(read(rel).splitlines(), 1):
                if names_model(line):
                    found.append("%s:%d: %s" % (rel, n, line))
        self.assertEqual(found, [])

    def test_검사가_모델_이름을_잡는다(self):
        for line in ("model: opus", "  model: x", '"model": "x"', "Sonnet 으로 돈다", "Sonnet으로 돈다", "opus를 쓴다",
                     "--model claude-opus-5-5"):
            self.assertTrue(names_model(line), line)
        for line in ("--model <워커 모델>", "disable-model-invocation: true", "모델은 쓰는 사람이 고른다"):
            self.assertFalse(names_model(line), line)


class NonstopCleanupTest(unittest.TestCase):
    def setUp(self):
        self.nonstop = read("skills/nonstop/SKILL.md")
        self.cleanup = section(read("skills/dispatch/SKILL.md"), "정리")

    def test_nonstop_은_병합된_작업의_워크트리와_브랜치를_dispatch_의_정리대로_지운다(self):
        body = section(self.nonstop, "작업이 병합되면")
        self.assertIn("`dispatch/SKILL.md` 의 「정리」", body)
        for word in ("워크트리", "브랜치", "PR 까지만", "hold", "blocked"):
            self.assertIn(word, body)

    def test_가리킨_dispatch_정리에_검사와_브랜치_삭제가_있다(self):
        self.assertIn("**워크트리를 검사한다.**", self.cleanup)
        self.assertIn("**브랜치를 지운다.**", self.cleanup)
        self.assertIn("headRefOid", self.cleanup)
        # PR 이 없는 레포(원격 없음)에서도 견줄 것이 있다
        self.assertIn("PR 이 없으면", self.cleanup)

    def test_병합된_작업은_job_의_보고를_마친_뒤에_워크트리를_지운다(self):
        # 8번 보고의 gh pr comment 와 show --save 는 워크트리의 기록을 읽는다
        body = section(self.nonstop, "작업이 병합되면")
        self.assertIn("`job` 의 8번 보고를 마친 뒤에", body)
        self.assertNotIn("`job` 의 보고는 PR 본문에 남긴다", self.nonstop)

    def test_정리의_검사를_nonstop_에_복사하지_않는다(self):
        self.assertNotIn("headRefOid", self.nonstop)
        self.assertNotIn("status --porcelain", self.nonstop)


class DispatchQuestionTest(unittest.TestCase):
    def setUp(self):
        self.text = read("skills/dispatch/SKILL.md")

    def test_도는_워커에_기준을_더하는_메시지를_보내지_않는다(self):
        self.assertIn("도는 중인 워커에 기준을 더하는 메시지를 보내지 않는다", self.text)
        self.assertIn("턴을 끝낸 뒤", self.text)

    def test_도는_워커에_말을_걸었으면_직전_보고_전문을_옮긴다(self):
        self.assertIn("직전 보고 전문", self.text)


class JobQuestionTextTest(unittest.TestCase):
    def test_보고_단계가_답_없는_질문을_맨_위에_다시_적게_한다(self):
        text = read("skills/job/SKILL.md")
        self.assertIn("job.py ask", text)
        self.assertIn("답을 받지 못한 질문", text)


def step(text, title):
    """`8. **보고**` 처럼 번호 붙은 단계 한 줄."""
    m = re.search(r"^\d+\. \*\*%s\*\*.*$" % re.escape(title), text, re.M)
    if not m:
        raise AssertionError("단계가 없다: " + title)
    return m.group(0)


class ShortCallTextTest(unittest.TestCase):
    """`job.py`, `nonstop.py` 는 bin/ 을 거쳐 PATH 의 명령으로 부른다. 긴 경로를 줄이려 지어낸 셸 변수가 zsh 에서 깨졌다."""

    def test_job_스킬은_PATH_의_job_py_를_부르고_못_찾을_때의_한_가지_모양을_둔다(self):
        text = read("skills/job/SKILL.md")
        self.assertIn("`bin/`", text)
        self.assertIn("PATH", text)
        self.assertIn('python3 "${CLAUDE_SKILL_DIR}/job.py"', text)
        self.assertIn("변수", text)  # 변수에 담지 않는다

    def test_스킬과_에이전트의_글은_스크립트를_스킬_폴더_경로로_부르지_않는다(self):
        found = []
        for rel in plugin_files():
            if not rel.endswith(".md"):
                continue
            for word in ("skills/job/job.py", "nonstop/nonstop.py", "이 스킬 폴더의 `job.py`", "이 스킬 폴더의 `nonstop.py`"):
                if word in read(rel):
                    found.append("%s: %s" % (rel, word))
        self.assertEqual(found, [])


class ReportTextTest(unittest.TestCase):
    """보고에 기록 전문을 다시 쓰지 않는다. PR 이 있으면 PR 에, 없으면 파일에 두고 가리킨다."""

    def test_보고는_전문을_다시_쓰지_않고_PR_의_기록이나_기록_파일을_가리킨다(self):
        report = step(read("skills/job/SKILL.md"), "보고")
        self.assertNotIn("출력을 그대로 붙이", report)
        self.assertIn("job.py show --full | gh pr comment", report)  # PR 을 연 뒤 바뀐 기록까지 담은 지금 기록
        self.assertIn("job.py show --save", report)
        self.assertIn("절대 경로", report)
        self.assertIn("한 줄", report)  # 기준마다 한 줄 요약

    def test_병합_단계는_기록_댓글을_보고_단계에_맡긴다(self):
        merge = read("skills/job/stages/merge.md")
        self.assertNotIn("PR 에 같은 내용을 댓글로 남긴다", merge)
        self.assertIn("보고 단계에서", merge)

    def test_증거_단계는_log_가_출력_끝을_늘_보인다고_하지_않는다(self):
        evidence = read("skills/job/stages/evidence.md")
        self.assertNotIn("끝 40줄만 보인다", evidence)
        self.assertIn("종료 코드가 0 이 아니면", evidence)

    def test_dispatch_완료_판단은_PR_의_기록이나_기록_파일을_읽어_대조한다(self):
        body = section(read("skills/dispatch/SKILL.md"), "4. 완료 판단")
        self.assertNotIn("워커가 보고에 붙인 원본 증거", body)
        self.assertIn("gh pr view", body)
        self.assertIn("기록 파일", body)
        self.assertNotIn("보고의 `job.py show` 출력", body)

    def test_댓글이_실패해_파일에만_있는_기록도_nonstop_과_dispatch_가_찾는다(self):
        self.assertIn("댓글이 실패하면", section(read("skills/dispatch/SKILL.md"), "4. 완료 판단"))
        self.assertIn("댓글이 실패", section(read("skills/nonstop/SKILL.md"), "작업이 병합되면"))

    def test_hardener_는_PR_이나_기록_파일에서_기록을_읽는다(self):
        hardener = read("agents/hardener.md")
        self.assertNotIn("`job.py show` 출력.", hardener)
        self.assertIn("기록 파일", hardener)


BODY_WORD = re.compile(r"본문|PR (body|description)|本文|正文", re.I)


def sentences(text):
    """글을 문장으로 나눈다. 줄바꿈과 문장 끝 마침표(., 。)에서 끊는다."""
    return [s for s in re.split(r"(?<=\.)\s+|(?<=。)|\n", text) if s.strip()]


def pastes_full_into_body(text):
    """PR 본문을 말하는 문장이 기록 전문(`show --full`)도 말하면 그 문장들. 전문을 본문에 붙이게 하는 글이다."""
    return [s for s in sentences(text) if BODY_WORD.search(s) and "--full" in s]


class PrBodyTextTest(unittest.TestCase):
    """PR 본문은 사람이 읽는 요약이다. 기록 전문을 붙였더니 본문이 13만 자가 되어 GitHub 한도(65,536자)에 걸렸다."""

    def setUp(self):
        self.pr = read("skills/job/stages/pr.md")
        self.body = re.search(r"^2\. .*?(?=^3\. )", self.pr, re.M | re.S).group(0)  # 본문을 정하는 2번

    def test_어느_글도_PR_본문에_기록_전문을_붙이게_하지_않는다(self):
        found = []
        for rel in plugin_files() + ["README.md", "README.en.md", "README.ja.md", "README.zh.md"]:
            found += ["%s: %s" % (rel, s) for s in pastes_full_into_body(read(rel))]
        self.assertEqual(found, [])

    def test_검사가_전문을_본문에_붙이는_옛_문장을_잡는다(self):
        for old in ("2. 커밋하고 push 하고, 브랜치에 PR 이 없으면 연다. 본문 맨 앞에 결과를 쓰고, 그 아래에 "
                    "`job.py show --full` 의 출력을 붙인다(로그 파일은 이 맥에만 있어서 내용째 붙인다).",
                    "- 기록을 볼 때는 `job.py show` 를 쓴다. `job.py show --full` 은 PR 본문과 PR 댓글에 붙일 때만 돌린다.",
                    "--full 이면 명령 전문도 붙인다. PR 본문에는 --full 을 붙인다.",
                    "Paste the `job.py show --full` output into the PR body.",
                    "Put `job.py show --full` in the PR description."):
            self.assertTrue(pastes_full_into_body(old), old)
        for new in ("본문은 사람이 읽는 요약이다. 기록 전문은 보고 단계에서 PR 댓글로 단다.",
                    "PR 이 있으면 `job.py show --full | gh pr comment <PR 번호> --body-file -` 로 단다."):
            self.assertFalse(pastes_full_into_body(new), new)

    def test_PR_단계는_명령_출력을_본문에_붙이지_않고_전문은_댓글로_돌린다(self):
        self.assertNotIn("show --full", self.pr)
        self.assertNotIn("내용째 붙인다", self.pr)
        self.assertIn("요약", self.body)
        self.assertIn("기록 댓글", self.body)

    def test_PR_본문에는_중요한_것만_요약해_둔다(self):
        for word in ("- 결과:", "중요한 것", "- 되돌릴 수 있는가:", "- 고른 것과 이유:", "- 고치지 못한 것:", "- 완료 기준:",
                     "한 줄"):
            self.assertIn(word, self.body)

    def test_dispatch_는_PR_본문에서_기록_전문을_찾지_않는다(self):
        dispatch = read("skills/dispatch/SKILL.md")
        self.assertNotIn("PR 본문", section(dispatch, "4. 완료 판단"))
        self.assertNotIn("결과는 PR(본문과 기록 댓글)에 남는다", dispatch)

    def test_기록_댓글이_실패하면_hardener_와_보고는_기록_파일을_가리킨다(self):
        # 본문에 전문이 없으니, PR 은 있어도 댓글이 실패하면 기록 전문은 `show --save` 의 파일에만 있다
        dispatch = section(read("skills/dispatch/SKILL.md"), "4. 완료 판단")
        self.assertNotIn("PR 이 없으면 기록 파일의 경로를 준다", dispatch)
        self.assertIn("댓글이 실패했으면 기록 파일의 경로를 준다", dispatch)
        hardener = read("agents/hardener.md")
        self.assertNotIn("PR 이 없으면 기록 파일", hardener)
        self.assertIn("댓글이 실패했으면 기록 파일", hardener)
        report = step(read("skills/job/SKILL.md"), "보고")
        self.assertNotIn("(PR 이 없으면 `show --save`", report)
        self.assertIn("댓글이 실패했으면 `show --save`", report)


class CommitTextTest(unittest.TestCase):
    """커밋은 끝에 한 번이 아니라 뜻이 갈리는 단계마다 나눈다. 세부는 커밋이 맡고 PR 본문은 요약한다."""

    def setUp(self):
        self.commit = section(read("skills/job/SKILL.md"), "커밋")

    def test_job_은_뜻이_갈리는_단계마다_커밋하고_메시지에_무엇을_왜를_쓴다(self):
        for word in ("실패하는 테스트", "구현", "막는 지적", "사소한 지적", "무엇을 왜"):
            self.assertIn(word, self.commit)

    def test_리뷰_뒤에는_고칠_때만_커밋하고_사소한_지적은_한_커밋으로_모은다(self):
        self.assertIn("고칠 것이 있을 때만 커밋", self.commit)
        self.assertIn("한 커밋", self.commit)  # review --minor 는 앞 리뷰 뒤의 커밋이 하나일 때만 받는다
        self.assertIn("review.md", self.commit)  # --minor 조건은 review.md 에만 둔다
        self.assertNotIn("--minor", self.commit)

    def test_병합_방식과_메시지_형식은_레포_규칙에_맡긴다(self):
        self.assertIn("레포의 규칙", self.commit)

    def test_테스트_먼저_단계는_실패하는_테스트만_따로_커밋한다(self):
        text = read("skills/job/stages/test-first.md")
        self.assertIn("테스트만 담아 커밋", text)
        self.assertIn("구현 커밋에 함께 담는다", text)  # 커밋 검사가 실패하는 테스트를 받지 않는 레포
        # 실패 이유를 읽은 뒤에 커밋한다. 문법 오류로 실패한 테스트를 커밋하지 않게
        self.assertLess(text.index("실패 출력의 끝을 읽는다"), text.index("테스트만 담아 커밋"))
        self.assertIn("사소한 지적", text)  # 사소한 지적의 테스트는 따로 커밋하지 않는다

    def test_리뷰_단계는_막는_지적마다_커밋을_나눈다(self):
        self.assertIn("지적마다 커밋", step(read("skills/job/stages/review.md"), "막는 지적만 고친다."))

    def test_PR_단계에서_몰아_커밋하지_않는다(self):
        self.assertNotIn("커밋하고 push", read("skills/job/stages/pr.md"))


class DispatchConditionsTest(unittest.TestCase):
    """dispatch 는 워커를 띄우는 방법을 정하지 않는다. 지금 환경이 주는 방법 가운데 조건을 모두 채우는 것으로 띄운다."""

    METHOD_WORDS = ("claude -p", "start_session", "세션 도구", "데스크톱 앱", "Remote Control", "보관 도구", "--permission-mode",
                    "use_worktree", "wake_when_done", ".claude/worktrees", "CLI (")
    CONDITIONS = ("자기 워크트리", "같은 환경", "사람 없이 끝까지", "끝을 안다", "말을 건다", "넘겨받는다")

    def setUp(self):
        self.text = read("skills/dispatch/SKILL.md")

    def test_dispatch_글에_특정_방법의_이름이_없다(self):
        for word in self.METHOD_WORDS:
            self.assertNotIn(word, self.text, word)

    def test_README_의_dispatch_설명에_특정_방법의_이름이_없다(self):
        for name in ("README.md", "README.en.md", "README.ja.md", "README.zh.md"):
            line = [l for l in read(name).splitlines() if l.startswith("- `dispatch`")][0]
            for word in self.METHOD_WORDS + ("desktop app", "デスクトップアプリ", "桌面应用", "session tool"):
                self.assertNotIn(word, line, (name, word))

    def test_조건_표가_남아_있다(self):
        table = section(self.text, "2. 워커 띄우기")
        for word in self.CONDITIONS:
            self.assertIn("| %s |" % word, table)

    def test_방법과_무관하게_지킬_것이_있다(self):
        body = section(self.text, "2. 워커 띄우기")
        for word in ("환경이 주는 방법", "이미 떠 있는지", "실제로 무엇이 생겼는지", "등록", "권한 검사를 끄는",
                     "스스로 깨어날 수 없으면", "한 대화를 두 곳에서", "도는 중인 워커에 기준을 더하는 메시지를 보내지 않는다"):
            self.assertIn(word, body, word)

    def test_정리는_환경이_주는_방법으로_닫고_워크트리까지_지우는지_먼저_본다(self):
        cleanup = section(self.text, "정리")
        self.assertIn("환경이 주는 방법", cleanup)
        self.assertIn("워크트리까지 지우는지", cleanup)


class RepoWayTest(unittest.TestCase):
    """레포만의 방식이 있으면 워커가 판단해 따른다. 강제하는 검사나 찾아 읽는 단계는 두지 않는다."""

    def setUp(self):
        self.text = read("skills/job/SKILL.md")

    def test_레포의_방식을_따르되_기록은_job_py_로_남긴다(self):
        self.assertIn("레포만의 방식", self.text)
        self.assertIn("레포의 방식을 따른다", self.text)
        self.assertIn("기록은 `job.py` 로 남긴다", self.text)

    def test_사용자_없음의_push_PR_병합보다_레포의_승인_규칙이_이긴다(self):
        unattended = section(self.text, "사용자 없음일 때")
        self.assertIn("레포의 승인 규칙", unattended)
        self.assertIn("레포가 이긴다", unattended)
        self.assertIn("job.py stop", unattended)


if __name__ == "__main__":
    unittest.main()
