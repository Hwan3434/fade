"""검사를 지키는 검사: 훅이 죽으면 테스트가 실패하는가, 감싸는 명령의 표가 하나인가, 줄 나누기, 특정 앱 이름, README 언어."""
import glob
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))

import merge_gate  # noqa: E402
from helpers import GATE, READMES, ROOT, hook  # noqa: E402

job = merge_gate.job
APP_NAMES = ("데스크톱", "desktop", "code 탭", "claude cli", "cowork", "claude.ai")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class HookHelperTest(unittest.TestCase):
    def test_훅이_죽으면_실패하고_일부러_죽인_테스트만_연다(self):
        with self.assertRaises(AssertionError):
            hook(GATE, "{깨진")
        self.assertEqual(hook(GATE, "{깨진", crash=True).stdout.strip(), "")


class WrapperTableTest(unittest.TestCase):
    """병합 훅과 job.py 가 감싸는 명령의 옵션 표를 한 곳에서 읽는다. 둘이 따로 있을 때 이미 어긋나 있었다."""

    def test_job_py_도_감싸는_명령의_긴_옵션의_값을_명령으로_보지_않는다(self):
        self.assertEqual(job.command_words("env --chdir /tmp python3 x.py")[0], ["env", "python3", "x.py"])
        self.assertEqual(job.command_words("sudo --user root python3 x.py")[0], ["sudo", "python3", "x.py"])

    def test_병합_훅도_job_py_가_감싸는_명령으로_보는_xargs_를_뗀다(self):
        self.assertEqual(merge_gate.unwrapped(["xargs", "-n", "1", "git", "push"]), ["git", "push"])


class SplitlinesTest(unittest.TestCase):
    """splitlines() 는 \\x0c, U+2028 같은 글자에서도 줄을 자른다. git 과 Read 는 \\n 으로만 줄을 센다."""

    def test_훅과_스크립트에_splitlines_가_없다(self):
        found = []
        for folder in ("hooks", "skills", "bin"):
            for path in glob.glob(os.path.join(ROOT, folder, "**", "*.py"), recursive=True):
                with open(path, encoding="utf-8") as f:
                    found += ["%s:%d" % (os.path.relpath(path, ROOT), n) for n, line in enumerate(f, 1)
                              if ".splitlines(" in line]
        self.assertEqual(found, [])


class AppNamesTest(unittest.TestCase):
    """fade 는 Claude Code 전용이지만 특정 앱에 묶이지 않는다. 훅과 job.py 주석의 동작 차이 설명은 사실이라 보지 않는다."""

    def test_스킬과_에이전트의_글과_두_설명에_특정_앱_이름이_없다(self):
        texts = {rel: read(rel) for rel in [os.path.relpath(p, ROOT) for folder in ("skills", "agents")
                                            for p in glob.glob(os.path.join(ROOT, folder, "**", "*.md"), recursive=True)]}
        texts["plugin.json"] = json.loads(read(".claude-plugin/plugin.json"))["description"]
        market = json.loads(read(".claude-plugin/marketplace.json"))
        texts["marketplace.json"] = " ".join([market["description"]] + [p["description"] for p in market["plugins"]])
        found = [(rel, word) for rel, text in texts.items() for word in APP_NAMES if word in text.lower()]
        self.assertEqual(found, [])


class ReadmeTest(unittest.TestCase):
    def test_README_는_한국어와_영어_둘이고_서로를_가리킨다(self):
        self.assertEqual(sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "README*.md"))), sorted(READMES))
        for name in READMES:
            links = re.findall(r"\]\((README[^)]*\.md)\)", "\n".join(read(name).split("\n")[:5]))
            self.assertEqual(links, [n for n in READMES if n != name], name)

    def test_README_는_레포에_스킬_사본을_넣는_길을_안내하지_않는다(self):
        for name in READMES:
            self.assertFalse(".claude/skills/" in read(name), name)


if __name__ == "__main__":
    unittest.main()
