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

    def test_끝_줄이_앞줄과_같아도_앞부분만_읽은_것은_받지_않는다(self):
        # 줄을 집합으로 견주면 앞에서 본 같은 글자의 줄이 끝 줄을 덮는다. 같은 줄은 나온 횟수만큼 보여야 한다
        commit_file(self.cwd, "a.py", "a = 2\n" + "pass  # 같은 줄\n" * 6, "반복")
        self.assertEqual(job(self.cwd, "review-files", "main").returncode, 0)
        with open(self.patch, encoding="utf-8") as f:
            n = len(f.read().splitlines())
        self.t.prompt(MARKER)
        self.read_patch(shown=(1, n - 3))  # head 처럼 끝 세 줄을 빼고 읽었다
        self.assertIn("a.py", self.denied())
        self.read_patch()
        self.assertIsNone(self.gate())

    def test_접두어를_뗀_내용만_읽은_것은_diff_를_읽은_것이_아니다(self):
        # 바뀐 파일을 cat 으로 읽으면 +, -, 공백 접두어가 없다. 접두어까지 견줘야 diff 를 읽었다고 친다
        text = "\n".join(l[1:] if l[:1] in "+- " else l for l in self.patch_text().splitlines())
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat a.py"}, result=text)
        self.denied()

    def test_앞_리뷰_전에_읽은_것은_다음_리뷰의_증거가_아니다(self):
        early = time.time()
        self.t.prompt(MARKER)
        time.sleep(0.01)
        self.assertEqual(job(self.cwd, "review", "1", "막는 지적 하나").returncode, 0)  # 이 리뷰 뒤로 자른다
        commit_file(self.cwd, "b.py", "b = 1\n", "고친 커밋")
        self.assertEqual(job(self.cwd, "review-files", "main").returncode, 0)
        # 앞 리뷰 전에 찍힌 출력에 새 bug.patch 의 줄이 다 들어 있어도 치지 않는다
        self.t._write(self.t.path, {"type": "user", "timestamp": iso(early), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": self.patch_text()}]}})
        self.assertIn("code-review", self.denied())

    def test_같은_커밋에서_리뷰를_다시_남기면_앞_리뷰가_본_것으로_받는다(self):
        # --dropped 를 빠뜨려 같은 커밋에서 다시 적는 경우. 새 커밋이 없으니 앞 리뷰를 받은 그 읽기로 판정한다
        self.t.prompt(MARKER)
        self.read_patch()
        self.assertIsNone(self.gate())
        time.sleep(0.01)
        self.assertEqual(job(self.cwd, "review", "1", "막는 지적 하나").returncode, 0)
        time.sleep(0.01)
        self.assertIsNone(self.gate("job.py review 0 \"오탐 하나\" --dropped=1"))

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

    def test_같은_앞부분을_두_번_읽어도_끝_줄을_읽은_것이_아니다(self):
        # 잘린 Read 를 다시 부르는 일은 흔하다. 끝 줄이 앞부분에 나온 줄과 같아도 그 자리를 읽어야 한다
        commit_file(self.cwd, "a.py", "def f():\n    if x:\n        y()\n    }\n}\n" * 2, "닫는 줄")
        self.assertEqual(job(self.cwd, "review-files", "main").returncode, 0)
        with open(self.patch, encoding="utf-8") as f:
            n = len(f.read().splitlines())
        self.t.prompt(MARKER)
        self.read_patch(shown=(1, n - 2))
        self.read_patch(shown=(1, n - 2))
        self.denied()
        self.read_patch(offset=n - 1, limit=2)
        self.assertIsNone(self.gate())

    def test_여러_hunk_파일을_읽다_잘리면_잘린_출력이라고_말한다(self):
        # 가장 흔한 실패(Read 가 앞부분만 돌려줌)에서 원인을 「범위가 다른 diff」로 거꾸로 말하지 않는다
        base = "".join("line %d\n" % i for i in range(80))
        subprocess.run(["git", "switch", "-q", "main"], cwd=self.cwd, check=True)
        commit_file(self.cwd, "b.py", base, "긴 파일")
        subprocess.run(["git", "switch", "-q", "feat/x"], cwd=self.cwd, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge", "-q", "--no-edit",
                        "main"], cwd=self.cwd, check=True)
        commit_file(self.cwd, "b.py", base.replace("line 5\n", "LINE 5\n").replace("line 40\n", "LINE 40\n")
                    .replace("line 75\n", "LINE 75\n"), "세 군데")
        self.assertEqual(job(self.cwd, "review-files", "main").returncode, 0)
        with open(self.patch, encoding="utf-8") as f:
            n = len(f.read().splitlines())
        self.t.prompt(MARKER)
        self.read_patch(shown=(1, n - 6))
        self.assertIn("잘린 출력", self.denied())

    def test_오류로_끝난_code_review_호출은_부른_것이_아니다(self):
        self.t.tool("Skill", {"skill": "code-review", "args": "medium x"}, result="Unknown skill: code-review", error=True)
        self.assertIn("code-review 가 돈 흔적이 없다", self.denied())

    def test_플러그인_이름이_붙은_code_review_도_부른_것이다(self):
        self.t.tool("Skill", {"skill": "anthropic:code-review", "args": "medium x"})
        out = self.raw({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                        "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}})
        self.assertIn("머리 글", out.get("systemMessage", ""))

    def test_해석하지_못해도_job_py_review_를_부르지_않는_명령에는_조용하다(self):
        for command in ('grep -rn "job.py review README.md', "echo 'job.py review-files 를 쓴다"):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                       "transcript_path": self.t.path, "tool_input": {"command": command}}
            self.assertEqual(self.raw(payload), {}, command)

    def test_오류로_끝나_내용이_없는_읽기는_읽은_것이_아니다(self):
        self.t.prompt(MARKER)
        self.t.tool("Read", {"file_path": self.patch}, result="error", error=True)
        self.denied()

    def patch_text(self):
        with open(self.patch, encoding="utf-8") as f:
            return f.read()

    def test_cat_으로_bug_patch_전체를_읽어도_받는다(self):
        # 실제 code-review 하위 에이전트는 bug.patch 를 Bash cat 으로 통째로 읽었다(PR 28 써 보기)
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat %s" % self.patch}, result=self.patch_text())
        self.assertIsNone(self.gate())

    def test_git_diff_출력에_diff_내용이_다_있으면_받는다(self):
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff main...HEAD"}, result=self.patch_text())
        self.assertIsNone(self.gate())

    def test_나눠_읽은_출력을_합쳐_다_보였으면_받는다(self):
        lines = self.patch_text().splitlines()
        half = len(lines) // 2
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "sed -n 1,%dp bug.patch" % half}, result="\n".join(lines[:half]))
        self.t.tool("Bash", {"command": "sed -n %d,$p bug.patch" % (half + 1)}, result="\n".join(lines[half:]))
        self.assertIsNone(self.gate())

    def test_앞부분만_보인_출력은_읽은_것이_아니고_빠진_줄을_알린다(self):
        with open(self.patch, "a") as f:
            f.write("".join("+줄 %d\n" % i for i in range(100)))
        lines = self.patch_text().splitlines()
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "head -40 bug.patch"}, result="\n".join(lines[:40]))
        self.t.tool("Bash", {"command": "git diff main...HEAD"},
                    result="Output too large (31.2KB). Full output saved to: x\n<persisted-output>\n" + "\n".join(lines[:20]))
        reason = self.denied()
        self.assertIn("a.py: 41-%d" % len(lines), reason)  # 41번 줄부터 끝까지 보이지 않았다
        self.assertIn("잘린 출력", reason)

    def test_숫자와_탭으로_시작하는_diff_줄도_cat_으로_읽으면_맞는다(self):
        with open(self.patch, "a") as f:
            f.write("12\t표의 한 줄\n")
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat bug.patch"}, result=self.patch_text())
        self.assertIsNone(self.gate())

    def test_폴더를_알_수_없는_review_는_세션_폴더의_기록으로_판정한다(self):
        self.assertIn("code-review", self.denied('cd "$WT" && job.py review 0 "x"'))

    def test_다른_파일의_diff_는_치지_않는다(self):
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff HEAD~1..HEAD -- other.py"}, result="diff --git a/other.py b/other.py\n+x")
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
        self.t.tool("Bash", {"command": "git diff main...feat/x && git ls-files"}, result=self.patch_text() + "\na.py", path=sub)
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
        self.t.tool("Bash", {"command": "git diff HEAD~1..HEAD"}, result=self.patch_text())  # 다시 하는 리뷰는 고친 부분만 봐도 된다
        self.assertIsNone(self.gate())

    def test_bug_patch_가_이_커밋에서_만든_것이_아니면_받지_않는다(self):
        self.t.prompt(MARKER)
        self.read_patch()
        commit_file(self.cwd, "a.py", "a = 3\n", "고침")
        self.assertIn("review-files", self.denied())

    def test_code_review_를_불렀는데_지시문의_머리_글을_못_찾으면_막지_않고_알린다(self):
        # code-review 는 fade 밖의 스킬이라 머리 글이 바뀔 수 있다. 바뀌었다고 모든 리뷰를 막지 않는다
        self.t.tool("Skill", {"skill": "code-review", "args": "medium %s" % self.patch})
        self.t.prompt(MARKER.replace("—", "-"))
        self.t.tool("Bash", {"command": "cat %s" % self.patch}, result=self.patch_text())
        out = self.raw({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                        "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}})
        self.assertNotIn("permissionDecision", out.get("hookSpecificOutput", {}))
        self.assertIn("머리 글", out["hookSpecificOutput"]["additionalContext"])
        self.assertIn("머리 글", out["systemMessage"])

    def test_사용자가_슬래시로_부른_code_review_도_부른_것으로_친다(self):
        self.t.prompt("<command-name>/code-review</command-name>\n<command-args>medium bug.patch</command-args>")
        self.t.prompt("바뀐 지시문")
        out = self.raw({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                        "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}})
        self.assertIn("머리 글", out.get("systemMessage", ""))
        self.assertNotIn("permissionDecision", out.get("hookSpecificOutput", {}))

    def test_code_review_를_부르지도_않았으면_막는다(self):
        self.t.tool("Skill", {"skill": "fade:try", "args": "x"})
        self.t.prompt(MARKER.replace("—", "-"))
        self.assertIn("code-review 가 돈 흔적이 없다", self.denied())

    def test_오류로_끝난_명령의_출력도_보인_것이다(self):
        # 종료 코드가 0 이 아닌 Bash 결과도 출력은 모델에 그대로 보인다(cat bug.patch; ls 없는파일)
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat bug.patch; ls 없는파일"},
                    result=self.patch_text() + "\nls: 없는파일: No such file or directory", error=True)
        self.assertIsNone(self.gate())

    def test_두_번에_나눈_code_review_의_합으로_받는다(self):
        lines = self.patch_text().splitlines()
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "head -3 bug.patch"}, result="\n".join(lines[:3]))
        self.t.prompt(MARKER)  # 나머지를 새 code-review 로 마저 읽었다
        self.t.tool("Bash", {"command": "tail -n +4 bug.patch"}, result="\n".join(lines[3:]))
        self.assertIsNone(self.gate())

    def test_하위_에이전트_둘에_나눈_code_review_의_합으로도_받는다(self):
        lines = self.patch_text().splitlines()
        for i, part in enumerate((lines[:3], lines[3:])):
            sub = self.t.subagent("bug%d" % i)
            self.t.tool("Skill", {"skill": "code-review", "args": "medium bug.patch"})
            self.t.prompt(MARKER, path=sub)
            self.t.tool("Bash", {"command": "cat"}, result="\n".join(part), path=sub)
        self.assertIsNone(self.gate())

    def test_합쳐도_덜_덮이면_막고_code_review_로_마저_읽으라고_한다(self):
        with open(self.patch, "a") as f:
            f.write("".join("+줄 %d\n" % i for i in range(20)))
        lines = self.patch_text().splitlines()
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "head"}, result="\n".join(lines[:10]))
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "sed"}, result="\n".join(lines[15:]))
        reason = self.denied()
        self.assertIn("a.py: 11-15", reason)
        self.assertIn("code-review 로 마저 읽는다", reason)
        self.assertIn("본체", reason)  # 본체가 읽은 것은 치지 않는다는 것을 알린다

    def test_조각을_부르지_않았으면_그_조각의_절대_경로와_원인을_알린다(self):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        big = "".join("value_%d = %d\n" % (i, i) for i in range(1500))
        commit_file(self.cwd, "big1.py", big, "큰 파일 하나")
        commit_file(self.cwd, "big2.py", big.replace("value", "other"), "큰 파일 둘")
        r = job(self.cwd, "review-files", "main")
        self.assertIn("parts/", r.stdout)
        first = os.path.join(self.cwd, ".fade-review", "parts", "01.patch")
        with open(first, encoding="utf-8") as f:
            text = f.read()
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat " + first}, result=text)
        reason = self.denied()
        rest = [n for n in sorted(os.listdir(os.path.dirname(first))) if n != "01.patch"]
        for name in rest:
            self.assertIn("`medium %s`" % os.path.join(os.path.realpath(self.cwd), ".fade-review", "parts", name), reason)
        self.assertIn("부르지 않은 것으로 보인다", reason)

    def test_CLI_에서_본체가_나머지를_읽은_것은_합에_치지_않는다(self):
        lines = self.patch_text().splitlines()
        self.t.tool("Skill", {"skill": "code-review", "args": "medium bug.patch"})
        sub = self.t.subagent("bug")
        self.t.prompt(MARKER, path=sub)
        self.t.tool("Bash", {"command": "head -3"}, result="\n".join(lines[:3]), path=sub)
        self.t.tool("Bash", {"command": "tail -n +4"}, result="\n".join(lines[3:]))  # 본체 기록
        self.denied()

    def test_범위가_다른_diff_를_읽었으면_그렇게_알린다(self):
        # 다시 하는 리뷰에서 bug.patch 대신 브랜치 전체 diff 를 읽으면 파일 머리는 같고 index 줄과 hunk 머리가 다르다
        other = []
        for line in self.patch_text().splitlines():
            if line.startswith("index "):
                line = "index 0000000..1111111 100644"
            elif line.startswith("@@"):
                line = "@@ -1,3 +1,4 @@"
            other.append(line)
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "git diff main...HEAD"}, result="\n".join(other))
        reason = self.denied()
        self.assertIn("범위가 다른 diff", reason)
        self.assertNotIn("잘린 출력", reason)

    def test_Binary_files_differ_줄은_읽을_줄로_치지_않는다(self):
        text = self.patch_text()
        with open(self.patch, "a") as f:
            f.write("Binary files a/logo.png and b/logo.png differ\n")
        self.t.prompt(MARKER)
        self.t.tool("Bash", {"command": "cat bug.patch"}, result=text)
        self.assertIsNone(self.gate())

    def test_표시된_파일만_바뀌어_bug_patch_가_비면_code_review_없이_받는다(self):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run(["git", "switch", "-q", "main"], cwd=self.cwd, check=True)
        commit_file(self.cwd, ".gitattributes", "gen.txt linguist-generated\n", "표시")
        subprocess.run(["git", "switch", "-q", "feat/x"], cwd=self.cwd, check=True)
        subprocess.run(git + ["reset", "-q", "--hard", "main"], cwd=self.cwd, check=True)
        commit_file(self.cwd, "gen.txt", "생성된 줄\n", "생성")
        r = job(self.cwd, "review-files", "main")
        self.assertIn("bug.patch 가 비었다", r.stdout)
        self.assertIsNone(self.gate())

    def test_같은_커밋에서_다시_만든_bug_patch_는_앞_리뷰가_본_범위라_비지_않는다(self):
        # 비면 code-review 없이 받힐 수 있다. 앞 리뷰와 같은 범위로 다시 만들어, 앞 리뷰가 본 code-review 로 판정한다
        before = self.patch_text()
        self.t.prompt(MARKER)
        self.read_patch()
        self.assertEqual(job(self.cwd, "review", "0", "버그 축만").returncode, 0)
        time.sleep(0.01)
        job(self.cwd, "review-files", "main")
        self.assertEqual(self.patch_text(), before)
        self.assertIsNone(self.gate())

    def test_같은_커밋의_다시_남기기도_앞_리뷰_뒤의_code_review_가_없으면_받지_않는다(self):
        self.assertEqual(job(self.cwd, "review", "0", "버그 축만").returncode, 0)  # 훅 없이 남긴 리뷰
        time.sleep(0.01)
        self.assertIn("code-review 가 돈 흔적이 없다", self.denied())

    def test_job_과_무관한_명령은_해석하지_못해도_조용하다(self):
        for command in ("echo 'oops", "cat <<'END-NOTES'\nit's\nEND-NOTES"):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                       "transcript_path": self.t.path, "tool_input": {"command": command}}
            self.assertEqual(self.raw(payload), {}, command)

    def test_해석하지_못한_review_는_막지_않되_알린다(self):
        self.passed_with_note({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                               "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x"}},
                              "판정하지 못했다")

    def test_python3_로_부른_review_도_보고_review_files_와_다른_명령은_보지_않는다(self):
        self.denied("python3 /x/skills/job/job.py review 0 \"버그 축만\"")
        self.assertIsNone(self.gate("job.py review-files main"))
        self.assertIsNone(self.gate("job.py show"))

    def raw(self, payload):
        r = subprocess.run([sys.executable, REVIEW_GATE], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def passed_with_note(self, payload, word):
        """판정할 수 없으면 막지 않되, 그 사실과 이유가 에이전트와 사용자에게 보인다."""
        out = self.raw(payload)
        self.assertNotIn("permissionDecision", out.get("hookSpecificOutput", {}))
        self.assertIn(word, out.get("hookSpecificOutput", {}).get("additionalContext", ""))
        self.assertIn(word, out.get("systemMessage", ""))

    def test_기록_경로가_없으면_막지_않되_판정하지_못했다고_알린다(self):
        self.passed_with_note({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                               "tool_input": {"command": "job.py review 0 \"x\""}}, "세션 기록")

    def test_bug_patch_가_없으면_막지_않되_판이_다를_수_있다고_알린다(self):
        os.remove(self.patch)  # PATH 의 다른 판 job.py 가 review-files 를 돌리면 bug.patch 가 없다
        self.passed_with_note({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                               "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}},
                              "bug.patch")

    def test_훅이_죽어도_막지_않되_죽었다고_알린다(self):
        with open(self.t.path, "w") as f:
            f.write("{}\n")
        os.chmod(self.t.path, 0)  # 세션 기록을 읽지 못한다
        self.addCleanup(os.chmod, self.t.path, 0o644)
        self.passed_with_note({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd,
                               "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}},
                              "판정하지 못했다")

    def test_막은_뒤_실수_기록이_실패해도_JSON_은_하나다(self):
        self.t.prompt(MARKER)
        blocker = os.path.join(self.logs.name, "파일")
        open(blocker, "w").close()
        env = dict(os.environ, FADE_MISTAKES=os.path.join(blocker, "mistakes.jsonl"))  # 파일 아래에는 쓸 수 없다
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.cwd, "transcript_path": self.t.path,
                   "tool_input": {"command": "job.py review 0 \"x\""}}
        r = subprocess.run([sys.executable, REVIEW_GATE], input=json.dumps(payload), capture_output=True, text=True, env=env)
        out = json.loads(r.stdout)  # JSON 이 둘이면 여기서 깨진다
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_임시_폴더의_레포는_막지_않되_판정하지_않았다고_알린다(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        subprocess.run(["git", "init", "-q", d.name], check=True)
        commit_and_switch(d.name, "feat/x")
        job(d.name, "start", "작업")
        self.passed_with_note({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": d.name,
                               "transcript_path": self.t.path, "tool_input": {"command": "job.py review 0 \"x\""}},
                              "임시 폴더")

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

    def test_앞_리뷰_전의_slip_과_red_는_고친_흔적이_아니다(self):
        job(self.cwd, "slip", "review", "k", "앞 리뷰 전에 고침", env=self.env)
        self.assertEqual(job(self.cwd, "red", "false").returncode, 0)
        time.sleep(0.01)
        self.assertEqual(self.review("2", "그대로").returncode, 0)
        time.sleep(0.01)
        r = self.review("0", "다 고쳤다")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("slip", r.stderr)

    def test_값을_받는_옵션만_이름_등호_값_꼴을_받는다(self):
        r = job(self.cwd, "review", "2", "x", "--spec=1")
        self.assertIn("모르는 옵션: --spec=1", r.stderr)

    def test_dropped_는_0_이상의_정수다(self):
        for bad in ("--dropped=x", "--dropped=-1", "--dropped"):
            self.assertNotEqual(self.review("2", "x", bad).returncode, 0, bad)


class ReviewFilesTest(unittest.TestCase):
    """레포가 .gitattributes 로 읽을 대상이 아니라고 표시한 파일은 리뷰용 diff 에서 빼고, 뺀 이름과 줄 수를 남긴다.
    bug.patch 가 한 번에 읽기 어려운 크기면 파일 단위로 나눈 조각도 쓴다."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.cwd = d.name
        subprocess.run(["git", "init", "-q", "-b", "main", self.cwd], check=True)
        commit_file(self.cwd, "a.py", "a = 1\n", "처음")
        commit_and_switch(self.cwd, "feat/x")
        job(self.cwd, "start", "작업")

    def files(self, attributes, branch_attributes=None, **changes):
        """attributes 는 base(main)에 둔 표시, branch_attributes 는 이 브랜치가 더한 표시다."""
        if attributes is not None:
            subprocess.run(["git", "switch", "-q", "main"], cwd=self.cwd, check=True)
            commit_file(self.cwd, ".gitattributes", attributes, "표시")
            subprocess.run(["git", "switch", "-q", "feat/x"], cwd=self.cwd, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge", "-q", "--no-edit",
                            "main"], cwd=self.cwd, check=True)
        if branch_attributes is not None:
            commit_file(self.cwd, ".gitattributes", branch_attributes, "브랜치의 표시")
        for name, text in changes.items():
            commit_file(self.cwd, name.replace("_", "."), text, name)
        r = job(self.cwd, "review-files", "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = os.path.join(self.cwd, ".fade-review")
        with open(os.path.join(folder, "bug.patch"), encoding="utf-8") as f, \
                open(os.path.join(folder, "diff.patch"), encoding="utf-8") as g:
            return r.stdout, f.read(), g.read()

    def test_linguist_generated_로_표시된_파일은_빠지고_이름과_줄_수가_남는다(self):
        out, bug, spec = self.files("gen_txt linguist-generated\n".replace("_", "."), gen_txt="1\n2\n3\n", b_py="b = 1\n")
        self.assertNotIn("b/gen.txt", bug)
        self.assertNotIn("b/gen.txt", spec)
        self.assertIn("b = 1", bug)
        self.assertIn("3\t0\tgen.txt", out)
        self.assertIn("gen.txt(3줄, linguist-generated)", job(self.cwd, "show").stdout)

    def test_이_브랜치가_더한_표시는_빼지_않고_그_사실을_알린다(self):
        # 브랜치가 스스로 표시를 더해 자기 파일을 리뷰에서 빼지 못하게, base 의 .gitattributes 에 있는 표시만 본다
        out, bug, spec = self.files(None, branch_attributes="gen.txt linguist-generated\n", gen_txt="1\n2\n")
        self.assertIn("b/gen.txt", bug)
        self.assertIn("b/gen.txt", spec)
        self.assertIn("b/.gitattributes", bug)  # 표시의 변경 자체도 리뷰에 남는다
        self.assertIn("이 브랜치가 .gitattributes 를 바꿨다", out)
        self.assertNotIn("뺀 파일", out)

    def test_base_의_표시를_이_브랜치가_지워도_base_의_표시로_뺀다(self):
        out, bug, _ = self.files("gen_txt linguist-generated\n".replace("_", "."), branch_attributes="", gen_txt="1\n")
        self.assertNotIn("b/gen.txt", bug)
        self.assertIn("이 브랜치가 .gitattributes 를 바꿨다", out)

    def test_이_브랜치가_더한_diff_끄기_표시로_내용을_숨기지_못한다(self):
        # git diff 도 base 의 표시로 만든다. 브랜치가 -diff 를 더하면 Binary files ... differ 한 줄만 남았다
        out, bug, spec = self.files(None, branch_attributes="b.py -diff\nc.py binary\n", b_py="b = 1\n", c_py="c = 2\n")
        self.assertIn("+b = 1", bug)
        self.assertIn("+c = 2", bug)
        self.assertIn("+b = 1", spec)

    def test_한글_이름_파일도_뺀_줄_수와_조각_목록이_바로_나온다(self):
        out, bug, _ = self.files("한글_생성.txt linguist-generated\n".replace("_생성", "생성"), **{"한글생성_txt": "1\n2\n"})
        self.assertIn("한글생성.txt(2줄, linguist-generated)", out)
        big = "".join("v_%d = %d\n" % (i, i) for i in range(2500))
        out, _, _ = self.files(None, **{"큰파일_py": big, "작은_py": "s = 1\n"})
        self.assertIn("큰파일.py", out)
        self.assertNotIn("\\3", out)

    def test_표시된_파일이_아주_많아도_리뷰_파일을_만든다(self):
        subprocess.run(["git", "switch", "-q", "main"], cwd=self.cwd, check=True)
        commit_file(self.cwd, ".gitattributes", "gen/** linguist-generated\n", "표시")
        subprocess.run(["git", "switch", "-q", "feat/x"], cwd=self.cwd, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "merge", "-q", "--no-edit",
                        "main"], cwd=self.cwd, check=True)
        gen = os.path.join(self.cwd, "gen")
        os.makedirs(gen)
        name = "a_generated_file_with_a_rather_long_name_%05d.txt"
        for i in range(40000):  # 뺄 경로를 인자로 넘기면 인자 한도(macOS 1MB, Linux 2MB)를 넘는 길이
            with open(os.path.join(gen, name % i), "w") as f:
                f.write("x\n")
        subprocess.run(["git", "add", "gen"], cwd=self.cwd, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "생성"],
                       cwd=self.cwd, check=True)
        r = job(self.cwd, "review-files", "main")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("bug.patch 가 비었다", r.stdout)

    def test_linguist_generated_true_도_빠지고_표시가_남는다(self):
        out, bug, _ = self.files("gen_txt linguist-generated=true\n".replace("_", "."), gen_txt="1\n")
        self.assertNotIn("b/gen.txt", bug)
        self.assertIn("gen.txt(1줄, linguist-generated)", out)

    def test_diff_를_끈_글_파일도_줄_수가_남고_binary_는_바이너리로_남는다(self):
        out, _, _ = self.files("lock_txt -diff\nimg_dat binary\n".replace("_", "."), lock_txt="x\ny\n", img_dat="\0\1")
        self.assertIn("lock.txt(2줄, -diff)", out)
        self.assertIn("img.dat(binary)", out)

    def test_명세_리뷰어에게_주는_show_에_이번에_뺀_파일이_나온다(self):
        self.files("gen_txt linguist-generated\n".replace("_", "."), gen_txt="1\n")
        with open(os.path.join(self.cwd, ".fade-review", "show.txt"), encoding="utf-8") as f:
            self.assertIn("gen.txt(1줄, linguist-generated)", f.read())

    def test_diff_를_끈_파일과_binary_도_빠진다(self):
        out, bug, _ = self.files("lock_txt -diff\nimg_dat binary\n".replace("_", "."), lock_txt="x\n", img_dat="y\n")
        self.assertNotIn("b/lock.txt", bug)
        self.assertNotIn("b/img.dat", bug)

    def test_표시가_없거나_false_면_빠지지_않는다(self):
        out, bug, _ = self.files("gen_txt linguist-generated=false\n".replace("_", "."), gen_txt="1\n", other_txt="2\n")
        self.assertIn("b/gen.txt", bug)
        self.assertIn("b/other.txt", bug)
        self.assertNotIn("뺀 파일", out)

    def test_bug_patch_의_줄_수를_알린다(self):
        out, bug, _ = self.files(None, b_py="b = 1\n")
        self.assertIn("bug.patch: %d줄" % len(bug.splitlines()), out)

    def test_큰_bug_patch_는_파일_단위_조각으로도_쓴다(self):
        big = "".join("line_%d = %d\n" % (i, i) for i in range(1500))
        out, bug, _ = self.files(None, big1_py=big, big2_py=big, small_py="s = 1\n")
        parts = os.path.join(self.cwd, ".fade-review", "parts")
        names = sorted(os.listdir(parts))
        self.assertGreater(len(names), 1)
        joined = []
        for name in names:
            with open(os.path.join(parts, name), encoding="utf-8") as f:
                text = f.read()
            self.assertTrue(text.startswith("diff --git "), name)  # 파일 경계에서 나눈다
            joined.append(text)
            self.assertIn(os.path.join(".fade-review", "parts", name), out)
        self.assertEqual("".join(joined), bug)

    def test_작은_bug_patch_는_조각을_쓰지_않고_앞의_조각을_지운다(self):
        big = "".join("line_%d = %d\n" % (i, i) for i in range(3000))
        self.files(None, big_py=big)
        self.files(None, big_py="b = 1\n")
        self.assertFalse(os.path.exists(os.path.join(self.cwd, ".fade-review", "parts")))


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

    def test_CI_는_끝날_때까지_막고_기다리는_명령으로_본다(self):
        # 앱의 PR 상태 도구는 알림으로 답해, 그것을 기다리며 앱 워커가 턴을 끝냈다(PR 25). gh pr checks --watch 는 앱에서도 막고 기다린다
        pr = self.read("skills", "job", "stages", "pr.md")
        step = [line for line in pr.splitlines() if line.startswith("4. CI 가 끝날 때까지")][0]
        self.assertIn("gh pr checks <번호> --watch", step)
        self.assertNotIn("PR 상태 도구로", step)

    def test_보고는_SKILL_md_의_8번이라고_적는다(self):
        review = self.read("skills", "job", "stages", "review.md")
        self.assertNotIn(" 8번 보고", review.replace("SKILL.md 의 8번 보고", ""))

    def test_큰_diff_는_나눠_리뷰하고_표시는_레포가_정한다(self):
        review = self.read("skills", "job", "stages", "review.md")
        for word in ("parts/", "linguist-generated", ".gitattributes", "명세 리뷰어", "쪼갤 것을 권한다"):
            self.assertIn(word, review, word)

    def test_README_가_뺀_파일과_나눈_리뷰를_말한다(self):
        for name in ("README.md", "README.en.md", "README.ja.md", "README.zh.md"):
            text = self.read(name)
            for word in ("linguist-generated", "parts/"):
                self.assertIn(word, text, (name, word))

    def test_파이썬_파일이_문법_경고를_내지_않는다(self):
        # "\$" 같은 잘못된 이스케이프는 Python 3.12 부터 SyntaxWarning 이다
        import glob
        import warnings
        for path in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f, warnings.catch_warnings():
                warnings.simplefilter("error")
                compile(f.read(), path, "exec")

    def test_기다리는_명령으로_턴을_잇지_않는다(self):
        self.assertNotIn("기다리는 명령을 돌려 턴을 잇는다", self.read("skills", "job", "SKILL.md"))


if __name__ == "__main__":
    unittest.main()
