"""사용자에게 물은 것을 job 기록에 남기고, 답이 없는 질문은 show 첫머리에 다시 낸다."""
import unittest

from helpers import commit_and_switch, git_repo, job


class QuestionTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo()
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        commit_and_switch(self.cwd, "feat/x")
        self.assertEqual(job(self.cwd, "start", "작업").returncode, 0)

    def show(self, *extra):
        r = job(self.cwd, "show", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def test_답이_없는_질문은_상태_줄_바로_아래에_번호째_나온다(self):
        self.assertEqual(job(self.cwd, "ask", "A 와 B 중 무엇으로 할까").returncode, 0)
        self.assertEqual(job(self.cwd, "ask", "배포도 할까").returncode, 0)
        out = self.show()
        self.assertEqual(out[0], "상태: 진행 중")
        self.assertEqual(out[1:4], ["답을 받지 못한 질문 (보고 맨 위에 번호째 다시 적는다):",
                                    "1. A 와 B 중 무엇으로 할까", "2. 배포도 할까"])

    def test_답을_받은_질문은_첫머리에서_빠지고_기록에_남는다(self):
        job(self.cwd, "ask", "A 와 B 중 무엇으로 할까")
        job(self.cwd, "ask", "배포도 할까")
        r = job(self.cwd, "answered", "1", "A")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.show()
        self.assertEqual(out[1:3], ["답을 받지 못한 질문 (보고 맨 위에 번호째 다시 적는다):", "2. 배포도 할까"])
        self.assertIn("- 물은 것: 1. A 와 B 중 무엇으로 할까 → A", out)

    def test_모두_답하면_첫머리에_질문이_없다(self):
        job(self.cwd, "ask", "배포도 할까")
        job(self.cwd, "answered", "1", "하지 않는다")
        out = self.show()
        self.assertEqual(out[1], "")
        self.assertNotIn("답을 받지 못한 질문", "\n".join(out))

    def test_full_에도_같은_첫머리가_나온다(self):
        job(self.cwd, "ask", "배포도 할까")
        self.assertEqual(self.show("--full")[2], "1. 배포도 할까")

    def test_없는_번호나_빈_답은_받지_않는다(self):
        job(self.cwd, "ask", "배포도 할까")
        for args in (("2", "답"), ("x", "답"), ("1", "  "), ("1",)):
            r = job(self.cwd, "answered", *args)
            self.assertNotEqual(r.returncode, 0, args)
        self.assertIn("1. 배포도 할까", self.show())

    def test_빈_질문은_받지_않는다(self):
        self.assertNotEqual(job(self.cwd, "ask", " ").returncode, 0)

    def test_질문이_없던_옛_기록도_show_가_돈다(self):
        import json, os, subprocess
        d = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=self.cwd, capture_output=True,
                           text=True).stdout.strip()
        p = os.path.join(d, "fade-job.json")
        state = json.load(open(p, encoding="utf-8"))
        state.pop("questions", None)
        json.dump(state, open(p, "w", encoding="utf-8"))
        self.assertEqual(self.show()[0], "상태: 진행 중")
        self.assertEqual(job(self.cwd, "ask", "배포도 할까").returncode, 0)


if __name__ == "__main__":
    unittest.main()
