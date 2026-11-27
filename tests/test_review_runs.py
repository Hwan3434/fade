"""버그 축 리뷰가 실제로 diff 를 읽었을 때만 job.py review 를 받는다(리뷰 훅). 막는 지적 수가 줄면 그 사이 고친 흔적이 있어야 한다."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import ROOT, commit_and_switch, commit_file, job

REVIEW_GATE = os.path.join(ROOT, "hooks", "review_gate.py")
MARKER = "## Phase 0 — Gather the diff"  # code-review 스킬의 지시문 머리. 앱에서는 본체 기록에, CLI 에서는 하위 에이전트 기록에 든다


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000)


class Transcript:
    """세션 기록 파일(JSONL)을 꼴만 본떠 쓴다. 하위 에이전트 기록은 <기록 이름>/subagents/ 아래에 둔다."""

    def __init__(self, folder, name="session"):
        self.path = os.path.join(folder, name + ".jsonl")
        self.sub = os.path.join(folder, name, "subagents")
        self.n = 0
        open(self.path, "w").close()

    def _write(self, path, row):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def prompt(self, text, path=None):
        self._write(path or self.path, {"type": "user", "timestamp": iso(time.time()),
                                        "message": {"role": "user", "content": [{"type": "text", "text": text}]}})

    def tool(self, name, tool_input, result="ok", error=False, path=None):
        self.n += 1
        tid = "toolu_%d" % self.n
        self._write(path or self.path, {"type": "assistant", "timestamp": iso(time.time()), "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        self._write(path or self.path, {"type": "user", "timestamp": iso(time.time()), "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": error}]}})

    def subagent(self, agent):
        os.makedirs(self.sub, exist_ok=True)
        path = os.path.join(self.sub, "agent-%s.jsonl" % agent)
        open(path, "w").close()
        return path


class GateTest(unittest.TestCase):
    def setUp(self):
        # 리뷰 훅은 OS 임시 폴더의 레포(써 보기, 테스트)를 판정하지 않는다. 그래서 이 체크아웃의 git 폴더 안에 레포를 둔다
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        self.repo = tempfile.TemporaryDirectory(dir=common)
        self.addCleanup(self.repo.cleanup)
        self.cwd = self.repo.name
        subprocess.run(["git", "init", "-q", "-b", "main", self.cwd], check=True)
        commit_file(self.cwd, "a.py", "a = 1\n", "처음")
        commit_and_switch(self.cwd, "feat/x")
        commit_file(self.cwd, "a.py", "a = 2\n", "구현")
        self.logs = tempfile.TemporaryDirectory()
        self.addCleanup(self.logs.cleanup)
        self.t = Transcript(self.logs.name)
        time.sleep(0.01)
        self.assertEqual(job(self.cwd, "start", "작업").returncode, 0)
        time.sleep(0.01)
        r = job(self.cwd, "review-files", "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.patch = os.path.join(self.cwd, ".fade-review", "bug.patch")

    def gate(self, command="job.py review 0 \"버그 축만\""):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd, "transcript_path": self.t.path,
                   "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, REVIEW_GATE], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def denied(self, command="job.py review 0 \"버그 축만\""):
        out = self.gate(command)
        self.assertIsNotNone(out)
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    def read_patch(self, path=None, shown=None, **extra):
        """Read 도구처럼 줄 번호를 붙인 결과를 남긴다. shown 은 실제로 돌려준 줄 범위다(토큰 한도로 잘리면 앞부분만 온다)."""
        with open(self.patch, encoding="utf-8") as f:
            lines = f.read().splitlines()
        start = extra.get("offset", 1)
        end = min(len(lines), start - 1 + extra.get("limit", 2000))
        first, last = shown or (start, end)
        result = "\n".join("%6d\t%s" % (i, lines[i - 1]) for i in range(first, last + 1))
        self.t.tool("Read", dict({"file_path": self.patch}, **extra), result=result, path=path)

    def test_review_files_가_버그_축의_patch_를_쓴다(self):
        with open(self.patch, encoding="utf-8") as f:
            self.assertIn("+a = 2", f.read())

    def test_리뷰가_도구를_하나도_부르지_않았으면_받지_않는다(self):
        self.t.tool("Skill", {"skill": "code-review", "args": "medium"})
        self.t.prompt(MARKER)
        self.assertIn("bug.patch", self.denied())

    def test_code_review_뒤에_bug_patch_를_끝까지_읽었으면_받는다(self):
        self.t.prompt(MARKER)
        self.read_patch()
        self.assertIsNone(self.gate())

    def test_bug_patch_를_일부만_읽었으면_받지_않는다(self):
        with open(self.patch, "a") as f:
            f.write("".join("+%d\n" % i for i in range(3000)))  # 한 번에 읽는 2000줄을 넘긴다
        self.t.prompt(MARKER)
        self.read_patch()
        self.denied()
        self.read_patch(offset=2001, limit=2000)
        self.assertIsNone(self.gate())

    def test_토큰_한도로_앞부분만_돌아온_Read_는_끝까지_읽은_것이_아니다(self):
        with open(self.patch, "a") as f:
            f.write("".join("+%d\n" % i for i in range(300)))
        self.t.prompt(MARKER)
        self.read_patch(shown=(1, 259))  # limit 없이 읽었는데 앞 259줄만 왔다(PARTIAL view)
        self.denied()
        self.read_patch(offset=260, limit=259)
        self.assertIsNone(self.gate())

    def test_읽기가_실패했으면_치지_않는다(self):
        self.t.prompt(MARKER)
        self.t.tool("Read", {"file_path": self.patch}, result="error", error=True)
        self.denied()

    def test_첫_리뷰는_base_와의_전체_git_diff_도_받는다(self):
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff main...HEAD"}, result="diff --git a/a.py b/a.py")
        self.assertIsNone(self.gate())

    def test_파일을_줄이거나_잘린_git_diff_는_치지_않는다(self):
        self.t.prompt(MARKER)
        for command, result in (("git diff main...HEAD -- src", "x"), ("git diff --stat main...HEAD", "x"),
                                ("git diff main...HEAD", "Output too large (31.2KB). Full output saved to: x\n<persisted-output>")):
            self.t.tool("Bash", {"command": command}, result=result)
        self.denied()

    def test_첫_리뷰는_범위가_base_와의_전체가_아니면_받지_않는다(self):
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff HEAD~1..HEAD"}, result="diff")
        self.denied()

    def test_diff_를_읽은_것이_code_review_보다_앞이면_치지_않는다(self):
        self.read_patch()
        self.t.prompt(MARKER)
        self.denied()

    def test_명세_리뷰어가_다른_기록에서_읽은_것은_치지_않는다(self):
        self.t.prompt(MARKER)
        self.read_patch(path=self.t.subagent("reviewer"))
        self.denied()

    def test_CLI_처럼_code_review_가_하위_에이전트에서_돌았으면_그_기록을_본다(self):
        self.t.tool("Skill", {"skill": "code-review", "args": "medium"})
        sub = self.t.subagent("bug")
        self.t.prompt(MARKER, path=sub)
        self.t.tool("Bash", {"command": "git diff main...feat/x && git ls-files"}, result="diff", path=sub)
        self.assertIsNone(self.gate())

    def test_받은_리뷰보다_앞의_읽기는_다음_리뷰의_증거가_아니다(self):
        self.t.prompt(MARKER)
        self.read_patch()
        self.assertEqual(job(self.cwd, "review", "1", "버그 축만").returncode, 0)
        time.sleep(0.01)
        commit_file(self.cwd, "a.py", "a = 3\n", "고침")
        job(self.cwd, "review-files", "main")
        self.denied()
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff HEAD~1..HEAD"}, result="diff")  # 다시 하는 리뷰는 고친 부분만 봐도 된다
        self.assertIsNone(self.gate())

    def test_bug_patch_가_이_커밋에서_만든_것이_아니면_받지_않는다(self):
        self.t.prompt(MARKER)
        self.read_patch()
        commit_file(self.cwd, "a.py", "a = 3\n", "고침")
        self.assertIn("review-files", self.denied())

    def test_python3_로_부른_review_도_보고_review_files_와_다른_명령은_보지_않는다(self):
        self.denied("python3 /x/skills/job/job.py review 0 \"버그 축만\"")
        self.assertIsNone(self.gate("job.py review-files main"))
        self.assertIsNone(self.gate("job.py show"))

    def test_기록_경로가_없으면_판정하지_않는다(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                   "tool_input": {"command": "job.py review 0 \"x\""}}
        r = subprocess.run([sys.executable, REVIEW_GATE], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "")

    def test_임시_폴더의_레포는_판정하지_않는다(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        subprocess.run(["git", "init", "-q", d.name], check=True)
        commit_and_switch(d.name, "feat/x")
        job(d.name, "start", "작업")
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": d.name, "transcript_path": self.t.path,
                   "tool_input": {"command": "job.py review 0 \"x\""}}
        r = subprocess.run([sys.executable, REVIEW_GATE], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "")

    def test_훅이_등록되어_있다(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            self.assertIn("review_gate.py", f.read())


class DropTest(unittest.TestCase):
    """남은 막는 지적 수가 앞 리뷰보다 줄었는데 그 사이 slip 도 새 red 도 없으면 받지 않는다. 오탐이나 결정과 어긋나
    빼는 수는 --dropped=<수> 로 따로 받는다."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.cwd = d.name
        subprocess.run(["git", "init", "-q", self.cwd], check=True)
        commit_and_switch(self.cwd, "feat/x")
        self.log = os.path.join(self.cwd, ".git", "mistakes.jsonl")
        self.env = dict(os.environ, FADE_MISTAKES=self.log)
        job(self.cwd, "start", "작업")
        self.assertEqual(job(self.cwd, "review", "2", "막는 지적 둘").returncode, 0)
        time.sleep(0.01)

    def review(self, *args):
        return job(self.cwd, "review", *args, env=self.env)

    def test_고친_흔적_없이_줄면_받지_않는다(self):
        r = self.review("0", "다 고쳤다")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("slip", r.stderr)

    def test_slip_이_있으면_받는다(self):
        job(self.cwd, "slip", "review", "k", "고침", env=self.env)
        r = self.review("0", "고쳤다")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_새_red_가_있으면_받는다(self):
        self.assertEqual(job(self.cwd, "red", "false").returncode, 0)
        r = self.review("1", "하나 고쳤다")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_뺀_수는_인자로_받고_고친_것이_없으면_흔적이_없어도_된다(self):
        r = self.review("0", "둘 다 계획서의 결정과 어긋남", "--dropped=2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("뺀 막는 지적 2개", job(self.cwd, "show").stdout)

    def test_뺀_수보다_더_줄면_흔적이_있어야_한다(self):
        self.assertNotEqual(self.review("0", "하나는 오탐", "--dropped=1").returncode, 0)

    def test_새_지적이_나와_수가_늘거나_같으면_흔적이_없어도_된다(self):
        self.assertEqual(self.review("3", "새 지적이 하나 더").returncode, 0)
        self.assertEqual(self.review("3", "그대로").returncode, 0)

    def test_dropped_는_0_이상의_정수다(self):
        for bad in ("--dropped=x", "--dropped=-1", "--dropped"):
            self.assertNotEqual(self.review("2", "x", bad).returncode, 0, bad)


class TextTest(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
            return f.read()

    def test_리뷰_지적을_계획서와_대조한다(self):
        review = self.read("skills", "job", "stages", "review.md")
        self.assertIn("결정과 어긋남", review)
        self.assertIn("결정이 필요한 것", review)
        self.assertIn("--dropped", review)
        self.assertIn("bug.patch", review)

    def test_기다리는_명령으로_턴을_잇지_않는다(self):
        self.assertNotIn("기다리는 명령을 돌려 턴을 잇는다", self.read("skills", "job", "SKILL.md"))


if __name__ == "__main__":
    unittest.main()
