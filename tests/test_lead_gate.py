"""사람과 리드만 하는 일(사람이 볼 것 풀기, 대조와 hardener 기록, 병합된 워커의 워크트리 지우기)을 job 을 돈 세션이
스스로 하지 못하게 하는 훅과 그 기록 명령을 본다. 명령은 어느 것도 실행하지 않고, 훅에 JSON 입력만 넣는다."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import ROOT, git_repo, job

LEAD = os.path.join(ROOT, "hooks", "lead_gate.py")
DISPATCHED = "fade:job 스킬로 아래 계획서를 수행한다. 사용자: 없음\n\n# 작업: x"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd, check=True,
                   capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        repo = git_repo()
        self.addCleanup(repo.cleanup)
        self.main = os.path.realpath(repo.name)
        git(self.main, "commit", "-q", "--allow-empty", "-m", "x")
        git(self.main, "switch", "-q", "-C", "main")  # git init 의 기본 브랜치 이름과 같아도 된다
        self.wt = os.path.join(self.main, ".claude", "worktrees", "x")
        git(self.main, "worktree", "add", "-q", "-b", "feat/x", self.wt)
        logs = tempfile.TemporaryDirectory()
        self.addCleanup(logs.cleanup)
        self.logs = logs.name

    def start(self, *extra):
        r = job(self.wt, "start", "작업", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)

    def transcript(self, first="작업해 줘", commands=(), cwd=None):
        """세션 기록 파일: 첫 사용자 글과 Bash 호출들."""
        path = os.path.join(self.logs, "s%d.jsonl" % len(os.listdir(self.logs)))
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # job.py start 와 같은 때에 찍힌 기록
        rows = [{"type": "user", "timestamp": now, "cwd": cwd or self.main,
                 "message": {"role": "user", "content": first}}]
        for c in commands:
            rows.append({"type": "assistant", "timestamp": now, "cwd": cwd or self.main,
                         "message": {"role": "assistant", "content": [
                             {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": c}}]}})
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        return path

    def restamp(self, path, at):
        """세션 기록의 모든 줄의 시각을 at 으로 바꾼다."""
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
        for r in rows:
            r["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    def own(self, first="작업해 줘"):
        """이 작업을 시작한 세션의 기록."""
        return self.transcript(first, ["cd %s && job.py start --unattended \"작업\"" % self.wt])

    def gate(self, command, transcript, cwd=None):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd or self.main,
                   "transcript_path": transcript, "tool_input": {"command": command}}
        r = subprocess.run([sys.executable, LEAD], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        return out["permissionDecisionReason"] if out and out.get("permissionDecision") == "deny" else None


class LeadOnlyTest(Base):
    """사람 없는 작업을 돈 세션(그 하위 에이전트 포함)은 사람이 볼 것을 풀거나 대조와 hardener 를 기록하지 못한다."""

    def test_사람_없는_작업을_돈_세션은_스스로_풀지_못한다(self):
        self.start("--unattended")
        own = self.own()
        for command in ('cd %s && job.py human-done 1 "화면을 봤다"' % self.wt,
                        'cd %s && job.py contrasted "기준 셋 모두 맞음"' % self.wt,
                        'cd %s && job.py hardened "제안 없음"' % self.wt,
                        'cd %s >/dev/null && python3 /x/skills/job/job.py human-done 1 "봤다"' % self.wt,
                        'cd %s && job.py resume "승인을 받았다"' % self.wt):
            reason = self.gate(command, own)
            self.assertIsNotNone(reason, command)
            self.assertIn("스스로", reason)
        self.assertIsNotNone(self.gate('job.py human-done 1 "봤다"', own, cwd=self.wt))

    def test_사람_있는_작업이어도_dispatch_워커는_스스로_남기지_못한다(self):
        self.start()
        own = self.own(DISPATCHED.replace("사용자: 없음", "사용자: 있음"))
        self.assertIsNotNone(self.gate('cd %s && job.py contrasted "맞음"' % self.wt, own))

    def test_dispatch_워커는_start_를_어떻게_쳤든_스스로_남기지_못한다(self):
        self.start("--unattended")
        own = self.transcript(DISPATCHED, ['WT=%s; cd "$WT" && job.py start --unattended "작업"' % self.wt])
        self.assertIsNotNone(self.gate('cd %s && job.py human-done 1 "봤다"' % self.wt, own))
        self.assertIsNotNone(self.gate('cd %s && job.py hardened "없음"' % self.wt, self.transcript(DISPATCHED)))

    def test_하위_에이전트_기록의_start_도_본다(self):
        self.start("--unattended")
        main = self.transcript()
        sub = os.path.join(main[:-len(".jsonl")], "subagents")
        os.makedirs(sub)
        with open(main) as f, open(os.path.join(sub, "agent-a.jsonl"), "w") as g:
            g.write(f.read())
        with open(os.path.join(sub, "agent-a.jsonl"), "a", encoding="utf-8") as g:
            g.write(json.dumps({"type": "assistant", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "cwd": self.main, "message": {
                "content": [{"type": "tool_use", "id": "s", "name": "Bash",
                             "input": {"command": "cd %s && job.py start --unattended x" % self.wt}}]}}) + "\n")
        self.assertIsNotNone(self.gate('cd %s && job.py human-done 1 "봤다"' % self.wt, main))

    def test_감싸서_부른_job_py_도_본다(self):
        self.start("--unattended")
        for command in ('cd %s && timeout 30 python3 /x/job.py human-done 1 "ok"' % self.wt,
                        'cd %s && uv run job.py contrasted x' % self.wt, 'cd %s && python3 -W ignore job.py hardened x' % self.wt):
            self.assertIsNotNone(self.gate(command, self.own()), command)

    def test_폴더를_알_수_없는_start_만_있으면_이_세션의_시작으로_짐작하지_않는다(self):
        # 리드가 그 작업이 시작되기 몇 시간 전에 다른 써 보기에서 폴더 모르는 start 를 냈다가, 병합 뒤 hardened 를 막혔다
        self.start("--unattended")
        lead = self.transcript(commands=['cd "$TRY" && job.py start "써 보기"'] * 4)
        self.restamp(lead, time.time() - 10 * 3600)
        for command in ('cd %s && job.py hardened "제안 없음"' % self.wt, 'cd %s && job.py contrasted "맞음"' % self.wt):
            self.assertIsNone(self.gate(command, lead), command)
        self.restamp(lead, time.time())  # 같은 때에 냈어도 짐작하지 않는다
        self.assertIsNone(self.gate('cd %s && job.py hardened "제안 없음"' % self.wt, lead))

    def test_첫_사용자_글의_앞_조각이_메타_글이어도_dispatch_지시문을_찾는다(self):
        self.start()
        own = self.own()
        with open(own, encoding="utf-8") as f:
            rows = [json.loads(l) for l in f]
        rows[0]["message"]["content"] = [{"type": "text", "text": "<system-reminder>x</system-reminder>"},
                                         {"type": "text", "text": DISPATCHED}]
        with open(own, "w", encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
        self.assertIsNotNone(self.gate('cd %s && job.py contrasted x' % self.wt, own))

    def test_막을_조각이_없으면_세션_기록을_읽지_않는다(self):
        # 모든 Bash 호출에 걸리는 훅이라, 긴 세션 기록을 매번 읽지 않게 한다
        import importlib.util
        spec = importlib.util.spec_from_file_location("lead_gate_t", LEAD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.bash_calls = lambda path: 1 / 0
        self.assertIsNone(mod.problem("ls -la && git status", self.main, self.own()))

    def test_병합이_기록된_뒤에도_그_세션은_대조와_hardener_를_스스로_남기지_못한다(self):
        self.start("--unattended")
        self.assertEqual(job(self.wt, "merged", "abc1234").returncode, 0)
        own = self.own()
        for command in ('cd %s && job.py contrasted "맞음"' % self.wt, 'cd %s && job.py hardened "없음"' % self.wt):
            self.assertIsNotNone(self.gate(command, own), command)

    def test_dispatch_지시문으로_시작하지_않고_본문에_든_글귀는_워커가_아니다(self):
        self.start()
        own = self.own("job 스킬의 설명: 「" + DISPATCHED + "」로 시작하면 이 스킬을 쓴다")
        self.assertIsNone(self.gate('cd %s && job.py contrasted x' % self.wt, own))

    def test_다른_세션과_사람이_있는_작업의_세션은_푼다(self):
        self.start("--unattended")
        lead = self.transcript(commands=["git worktree list"])
        self.assertIsNone(self.gate('cd %s && job.py human-done 1 "리드가 화면을 봤다"' % self.wt, lead))
        self.assertIsNone(self.gate('cd %s && job.py contrasted "맞음"' % self.wt, lead))

    def test_사람이_있는_작업은_그_세션도_푼다(self):
        self.start()
        self.assertIsNone(self.gate('cd %s && job.py human-done 1 "사용자가 봤다"' % self.wt, self.own()))

    def test_세션_기록이_없으면_막지_않는다(self):
        self.start("--unattended")
        self.assertIsNone(self.gate('cd %s && job.py human-done 1 "봤다"' % self.wt, ""))


class RemoveTest(Base):
    """병합된 워커의 워크트리는 리드의 대조와 hardener 기록이 있어야 지운다. 스스로 시작한 작업(nonstop)의 정리,
    병합되지 않은 작업(닫힌 PR), job 기록이 없는 워크트리는 막지 않는다."""

    def merged(self):
        self.start("--unattended")
        self.assertEqual(job(self.wt, "merged", "abc1234", "CI 통과").returncode, 0)

    def removals(self):
        return ("git worktree remove %s" % self.wt, "git worktree remove --force .claude/worktrees/x",
                "git -C %s worktree remove %s" % (self.main, self.wt), "rm -rf %s" % self.wt,
                "cd %s && rm -rf x" % os.path.dirname(self.wt))

    def test_리드의_기록이_없으면_다른_세션이_지우지_못한다(self):
        self.merged()
        lead = self.transcript(commands=["gh pr view 3"])
        for command in self.removals():
            reason = self.gate(command, lead)
            self.assertIsNotNone(reason, command)
            self.assertIn("job.py contrasted", reason)
            self.assertIn("job.py hardened", reason)

    def test_대조와_hardener_를_기록하면_지운다(self):
        self.merged()
        lead = self.transcript()
        self.assertEqual(job(self.wt, "contrasted", "완료 기준 셋 모두 증거와 맞다").returncode, 0)
        self.assertIsNotNone(self.gate(self.removals()[0], lead))  # hardener 가 아직이다
        self.assertEqual(job(self.wt, "hardened", "제안 없음").returncode, 0)
        for command in self.removals():
            self.assertIsNone(self.gate(command, lead), command)
        show = job(self.wt, "show").stdout
        self.assertIn("완료 기준 셋 모두 증거와 맞다", show)
        self.assertIn("제안 없음", show)

    def test_스스로_시작한_작업의_정리는_막지_않는다(self):
        self.merged()
        self.assertIsNone(self.gate(self.removals()[0], self.own("/fade:nonstop 목록대로 해")))

    def test_dispatch_로_띄운_워커는_자기_워크트리도_지우지_못한다(self):
        self.merged()
        self.assertIsNotNone(self.gate(self.removals()[0], self.own(DISPATCHED)))

    def test_첫_사용자_글_앞의_메타_줄은_건너뛴다(self):
        self.merged()
        own = self.own(DISPATCHED)
        with open(own, encoding="utf-8") as f:
            rows = f.read()
        meta = json.dumps({"type": "user", "isMeta": True, "timestamp": "2026-01-01T00:00:00Z",
                           "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}})
        with open(own, "w", encoding="utf-8") as f:
            f.write(meta + "\n" + rows)
        self.assertIsNotNone(self.gate(self.removals()[0], own))

    def test_워크트리를_담은_폴더나_글롭으로_지워도_본다(self):
        self.merged()
        lead = self.transcript()
        for command in ("rm -rf %s/.claude/worktrees" % self.main, "rm -rf .claude/worktrees/*", "rm -rf .claude",
                        "git --no-pager worktree remove %s" % self.wt):
            self.assertIsNotNone(self.gate(command, lead), command)

    def test_홈_변수와_글롭과_중괄호와_기록_폴더_지우기도_본다(self):
        self.merged()
        lead = self.transcript()
        rel = os.path.relpath(self.wt, os.path.expanduser("~")) if self.wt.startswith(os.path.expanduser("~")) else None
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=self.main, capture_output=True,
                                text=True).stdout.strip()
        commands = ["rm -rf .claude/worktrees/x*", "rm -rf .claude/worktrees/{x,zz}", "rm --recursive %s" % self.wt,
                    "rm -rf %s" % os.path.join(self.main, common, "worktrees", "x")]
        if rel:
            commands.append('rm -rf "$HOME/%s"' % rel)
        for command in commands:
            self.assertIsNotNone(self.gate(command, lead), command)

    def test_끝_이름이_글롭뿐인_지우기는_그_폴더째로_본다(self):
        self.merged()
        lead = self.transcript()
        for command in ("rm -rf .claude/worktrees/x/.*", "rm -rf .claude/worktrees/x/*", "cd %s && rm -rf ./*" % self.wt):
            self.assertIsNotNone(self.gate(command, lead), command)
        self.assertIsNone(self.gate("cd %s && rm -rf *.log" % self.wt, lead))  # 맞는 것이 없는 이름 붙은 글롭은 아무것도 안 지운다

    def test_레포들을_담은_폴더_지우기도_그_레포들의_워크트리를_본다(self):
        self.merged()
        holder = os.path.dirname(self.main)  # 레포(메인 체크아웃)를 담은 git 아닌 폴더
        self.assertIsNotNone(self.gate("rm -rf " + holder, self.transcript()))

    def test_현재_폴더_변수로_가리킨_워크트리_지우기도_본다(self):
        self.merged()
        lead = self.transcript()
        for command in ('rm -rf "$PWD/.claude/worktrees/x"', "rm -rf ${PWD}/.claude/worktrees/x", 'rm -rf "$PWD"/.claude/worktrees/x',
                        "rm -rf $PWD/.claude/worktrees/x", 'rm -rf "$(pwd)/.claude/worktrees/x"', 'rm -rf "`pwd`/.claude/worktrees/x"',
                        'git worktree remove "$PWD/.claude/worktrees/x"'):
            self.assertIsNotNone(self.gate(command, lead), command)

    def test_레포_밖_워크트리를_가진_메인_체크아웃을_통째로_지워도_본다(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        wt = os.path.join(os.path.realpath(outside.name), "y")
        git(self.main, "worktree", "add", "-q", "-b", "feat/y", wt)
        self.assertEqual(job(wt, "start", "작업", "--unattended").returncode, 0)
        self.assertEqual(job(wt, "merged", "abc").returncode, 0)
        self.assertIsNotNone(self.gate("rm -rf " + self.main, self.transcript(), cwd=os.path.dirname(self.main)))

    def test_레포_밖_워크트리를_담은_git_아닌_폴더_지우기도_본다(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        wt = os.path.join(os.path.realpath(outside.name), "wts", "y")
        git(self.main, "worktree", "add", "-q", "-b", "feat/y", wt)
        self.assertEqual(job(wt, "start", "작업", "--unattended").returncode, 0)
        self.assertEqual(job(wt, "merged", "abc").returncode, 0)
        self.assertIsNotNone(self.gate("rm -rf " + os.path.dirname(wt), self.transcript()))

    def test_워크트리와_무관한_재귀_삭제에는_세션_기록을_읽지_않는다(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("lead_gate_t2", LEAD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.bash_calls = lambda path: 1 / 0
        os.makedirs(os.path.join(self.main, "build"))
        self.assertIsNone(mod.problem("rm -rf build", self.main, self.own()))

    def test_셸_변수로_시작한_작업의_정리는_리드_기록을_요구한다(self):
        self.merged()
        own = self.transcript("/fade:nonstop", ['cd "$WT" && job.py start --unattended "작업"'])
        self.assertIsNotNone(self.gate(self.removals()[0], own))

    def test_병합되지_않은_작업과_기록이_없는_워크트리는_막지_않는다(self):
        self.start("--unattended")
        self.assertIsNone(self.gate(self.removals()[0], self.transcript()))
        other = os.path.join(self.main, ".claude", "worktrees", "y")
        git(self.main, "worktree", "add", "-q", "-b", "feat/y", other)
        self.assertIsNone(self.gate("git worktree remove " + other, self.transcript()))

    def test_워크트리_안의_파일이나_하위_폴더_삭제는_막지_않는다(self):
        self.merged()
        self.assertIsNone(self.gate("rm -rf %s/.fade-review" % self.wt, self.transcript()))


class RecordTest(Base):
    """사람이 볼 것을 푼 근거와 리드의 대조, hardener 결과가 기록과 show 에 남는다."""

    def test_human_done_은_그_항목을_풀고_누가_무엇을_근거로_풀었는지_남긴다(self):
        self.start("--unattended")
        job(self.wt, "human", "앱 화면은 사람이 본다")
        job(self.wt, "human", "알림 소리는 사람이 듣는다")
        shot = os.path.join(self.wt, "shot.png")
        open(shot, "w").close()
        r = job(self.wt, "human-done", "1", "리드가 시뮬레이터 화면을 봤다", shot)
        self.assertEqual(r.returncode, 0, r.stderr)
        check = job(self.wt, "check").stdout
        self.assertNotIn("앱 화면은 사람이 본다", check)
        self.assertIn("알림 소리는 사람이 듣는다", check)
        show = job(self.wt, "show", "--full").stdout
        self.assertIn("리드가 시뮬레이터 화면을 봤다", show)
        self.assertIn(shot, show)

    def test_번호는_0_을_붙여도_같은_항목이고_숫자가_아닌_글자는_받지_않는다(self):
        self.start()
        self.assertEqual(job(self.wt, "human", "앱 화면").returncode, 0)
        r = job(self.wt, "human-done", "01", "봤다")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("앱 화면", job(self.wt, "check").stdout)
        r = job(self.wt, "human-done", "²", "봤다")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_푼_뒤_커밋이_바뀌면_다시_사람이_볼_것이_된다(self):
        self.start()
        self.assertEqual(job(self.wt, "human", "앱 화면").returncode, 0)
        self.assertEqual(job(self.wt, "human-done", "1", "봤다").returncode, 0)
        git(self.wt, "commit", "-q", "--allow-empty", "-m", "화면을 고침")
        check = job(self.wt, "check").stdout
        self.assertIn("앱 화면", check)
        self.assertIn("낡", check)
        self.assertIn("낡았다", job(self.wt, "show").stdout)  # show 도 풀린 것으로만 보이지 않는다

    def test_없는_번호와_빈_근거는_받지_않는다(self):
        self.start()
        job(self.wt, "human", "앱 화면")
        self.assertNotEqual(job(self.wt, "human-done", "2", "봤다").returncode, 0)
        self.assertNotEqual(job(self.wt, "human-done", "1", " ").returncode, 0)
        self.assertNotEqual(job(self.wt, "contrasted", " ").returncode, 0)

    def test_dispatch_와_job_글이_리드의_기록과_PR_까지만_작업의_병합_길을_말한다(self):
        with open(os.path.join(ROOT, "skills", "dispatch", "SKILL.md"), encoding="utf-8") as f:
            done = f.read().split("## 4. 완료 판단", 1)[1]
        for word in ("job.py contrasted", "job.py hardened", "job.py human-done", "job.py scope merge", "job.py tried",
                     "훅을 돌아가지 않는다", "job.py drop --tried", "job.py merged"):
            self.assertIn(word, done, word)
        with open(os.path.join(ROOT, "skills", "job", "SKILL.md"), encoding="utf-8") as f:
            self.assertIn("human-done", f.read())

    def test_훅이_등록되어_있다(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            self.assertIn("lead_gate.py", f.read())


if __name__ == "__main__":
    unittest.main()
