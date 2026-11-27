"""플러그인 에이전트 정의와 훅 등록을 본다. 에이전트의 도구 목록이 「읽기만」「고치지 않음」을 강제하는 장치다."""
import glob
import json
import os
import re
import unittest

from helpers import AGENTS, ROOT


def frontmatter(path):
    """맨 앞 --- 사이의 `키: 값` 줄. CI 에는 yaml 이 없어 직접 읽는다."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise AssertionError("frontmatter 가 없다: " + path)
    out = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out, text[m.end():]


def tool_set(value):
    return {t.strip() for t in value.split(",") if t.strip()}


class AgentsTest(unittest.TestCase):
    def agent(self, name):
        meta, body = frontmatter(os.path.join(AGENTS, name + ".md"))
        self.assertEqual(meta.get("name"), name)
        self.assertTrue(meta.get("description"), name)
        self.assertNotIn("model", meta, name)  # 모델은 쓰는 사람이 고른다. 에이전트가 정하면 본체 모델을 무시한다
        self.assertTrue(body.strip(), name)
        return meta, body

    def test_에이전트는_셋이다(self):
        self.assertEqual(sorted(os.path.basename(p) for p in glob.glob(os.path.join(AGENTS, "*.md"))),
                         ["hardener.md", "reviewer.md", "tester.md"])

    def test_reviewer_는_읽기_도구만_가진다(self):
        meta, _ = self.agent("reviewer")
        self.assertEqual(tool_set(meta["tools"]), {"Read", "Grep", "Glob"})

    def test_tester_는_편집_도구가_없다(self):
        meta, _ = self.agent("tester")
        self.assertNotIn("tools", meta)  # 브라우저·시뮬레이터 도구를 물려받아야 써 볼 수 있다
        self.assertTrue({"Edit", "Write", "NotebookEdit"} <= tool_set(meta["disallowedTools"]))

    def test_hardener_는_편집_도구가_없다(self):
        meta, _ = self.agent("hardener")
        self.assertFalse({"Edit", "Write", "NotebookEdit"} & tool_set(meta["tools"]))

    def test_에이전트는_사람마다_다른_값을_담지_않는다(self):
        for path in glob.glob(os.path.join(AGENTS, "*.md")):
            text = open(path, encoding="utf-8").read()
            for word in ("--squash", "--rebase", "squash", "feat/", "fix/", "/Users/"):
                self.assertNotIn(word, text, path)

    def test_에이전트가_가리키는_플러그인_파일이_있다(self):
        for path in glob.glob(os.path.join(AGENTS, "*.md")):
            for rel in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", open(path, encoding="utf-8").read()):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), path + " → " + rel)


class HooksTest(unittest.TestCase):
    def test_파괴적_명령_차단_훅이_모든_Bash_호출에_걸린다(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        commands = [h["command"] for entry in hooks["PreToolUse"] if entry.get("matcher") == "Bash"
                    for h in entry["hooks"]]
        self.assertIn('python3 -I "${CLAUDE_PLUGIN_ROOT}/hooks/destructive_gate.py"', commands)
        self.assertIn('python3 -I "${CLAUDE_PLUGIN_ROOT}/hooks/merge_gate.py"', commands)


if __name__ == "__main__":
    unittest.main()
