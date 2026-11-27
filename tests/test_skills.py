"""스킬, 에이전트, 훅의 글이 지켜야 하는 것을 소스에서 본다."""
import os
import re
import subprocess
import unittest

from helpers import ROOT

# 모델은 사람마다 고르는 값이다. fade 의 어디에 박혀도 쓰는 사람의 선택을 덮는다
MODEL_NAME = re.compile(r"\b(opus|sonnet|haiku|fable)\b|claude-[a-z]+-\d", re.I)


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
                if line.startswith("model:") or MODEL_NAME.search(line):
                    found.append("%s:%d: %s" % (rel, n, line))
        self.assertEqual(found, [])

    def test_검사가_모델_이름을_잡는다(self):
        for line in ("model: opus", "Sonnet 으로 돈다", "--model claude-opus-5-5"):
            self.assertTrue(line.startswith("model:") or MODEL_NAME.search(line), line)
        self.assertIsNone(MODEL_NAME.search("--model <워커 모델>"))


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


if __name__ == "__main__":
    unittest.main()
