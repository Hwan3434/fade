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
        self.assertIn("댓글이 실패하면", section(read("skills/nonstop/SKILL.md"), "작업이 병합되면"))

    def test_hardener_는_PR_이나_기록_파일에서_기록을_읽는다(self):
        hardener = read("agents/hardener.md")
        self.assertNotIn("`job.py show` 출력.", hardener)
        self.assertIn("기록 파일", hardener)


class DispatchRemoteTest(unittest.TestCase):
    def setUp(self):
        self.text = read("skills/dispatch/SKILL.md")
        self.desktop = section(self.text, "데스크톱 앱")

    def test_다른_폴더가_거부되면_같은_폴더에_띄우고_첫_지시문에서_워크트리를_만든다(self):
        for word in ("Remote Control", "같은 폴더", "`cwd` 없이", "`use_worktree` 를 끄고", "git worktree add",
                     "이후 모든 작업은 그 워크트리 안에서 한다"):
            self.assertIn(word, self.desktop)
        self.assertNotIn("떠 있는 세션이 있으면 메시지로 맡기고", self.desktop)

    def test_사용자_메시지_없이_시작한_턴에서_거부되면_사용자에게_청하거나_CLI_를_쓴다(self):
        self.assertIn("사용자의 메시지", self.desktop)
        self.assertIn("스스로 깨어난 턴에서는 같은 폴더의 세션도 거부된다", self.desktop)
        self.assertIn("없으면 아래 CLI 방법을 쓴다", self.desktop)

    def test_같은_폴더_워커에서_걸린_것을_적는다(self):
        # 훅과 job.py 는 세션의 폴더로 기록을 찾는다. git -C 만으로는 찾지 못한다
        self.assertIn("`cd`", self.desktop)
        self.assertIn("`git -C`", self.desktop)
        self.assertIn("훅", self.desktop)

    def test_워커가_만든_워크트리는_보관해도_남으니_리드가_지운다(self):
        cleanup = section(self.text, "정리")
        self.assertIn("보관해도", cleanup)
        self.assertIn("**워크트리를 검사한다.**", cleanup)
        self.assertIn("**브랜치를 지운다.**", cleanup)

    def test_description_은_Remote_Control_을_CLI_로만_보내지_않는다(self):
        description = re.search(r"^description: (.*)$", self.text, re.M).group(1)
        self.assertNotIn("(CLI, Remote Control)", description)


if __name__ == "__main__":
    unittest.main()
