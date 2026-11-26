import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "skills", "nonstop", "nonstop.py")


class NonstopTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def run_cmd(self, *args):
        env = dict(os.environ, HOME=self.home.name)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env)

    def tasks(self, session):
        with open(os.path.join(self.home.name, ".cache", "fade-nonstop", session, "tasks.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_init_만들고_다음_작업을_알린다(self):
        r = self.run_cmd("init", "s1", "첫 작업", "둘째 작업")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("남은 작업 2개 — 다음: 1. 첫 작업", r.stdout)
        self.assertEqual([t["title"] for t in self.tasks("s1")], ["첫 작업", "둘째 작업"])

    def test_남은_작업이_있으면_init_으로_덮어쓰지_않는다(self):
        self.run_cmd("init", "s1", "첫 작업")
        r = self.run_cmd("init", "s1", "새 작업")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("덮어쓰지 않는다", r.stderr)
        self.assertEqual([t["title"] for t in self.tasks("s1")], ["첫 작업"])

    def test_done_에는_메모가_있어야_한다(self):
        self.run_cmd("init", "s1", "첫 작업")
        r = self.run_cmd("set", "s1", "1", "done")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.tasks("s1")[0]["state"], "todo")

    def test_없는_상태는_거부한다(self):
        self.run_cmd("init", "s1", "첫 작업")
        r = self.run_cmd("set", "s1", "1", "finished", "메모")
        self.assertNotEqual(r.returncode, 0)

    def test_보고는_상태별로_묶고_PR_수를_센다(self):
        self.run_cmd("init", "s1", "가", "나", "다")
        self.run_cmd("set", "s1", "1", "done", "https://github.com/o/r/pull/3")
        self.run_cmd("set", "s1", "2", "hold", "질문")
        self.run_cmd("decide", "s1", "3", "권장안으로 정함")
        r = self.run_cmd("show", "s1")
        self.assertIn("PR 1개 · 변경 없이 끝남 0개 · 보류 1개 · 막힘 0개 · 남음 1개", r.stdout)
        self.assertIn("## 권장안으로 정한 것", r.stdout)
        self.assertIn("남은 작업 1개 — 다음: 3. 다", r.stdout)

    def test_세션_이름에_경로_문자를_받지_않는다(self):
        for bad in ("../x", "a/b", "$SESSION"):
            r = self.run_cmd("init", bad, "작업")
            self.assertNotEqual(r.returncode, 0, bad)


if __name__ == "__main__":
    unittest.main()
