#!/usr/bin/env python3
"""사람과 리드만 하는 일을 job 을 돈 세션이 스스로 하지 못하게 한다.

막는 것은 둘이다.
- 사람 없는 작업(`job.py start --unattended`)을 돈 세션과 dispatch 의 워커(사람이 있어도)가 그 작업의
  `job.py human-done`(사람이 볼 것 풀기), `contrasted`(리드의 대조), `hardened`(hardener 결과), `resume`(멈춤 풀기)을
  남기는 것. 사람이 볼 것을 그 작업이 스스로 풀면 human 이 뜻이 없다. 사람이 터미널에서 치거나, 사람이 맡긴 리드(다른
  세션)가 한다. 병합이 기록된 뒤에도 같다.
- 병합된 워커의 워크트리를 리드의 대조와 hardener 기록 없이 지우는 것: `git worktree remove`, 워크트리나 그것을 담은
  폴더(레포 밖의 git 아닌 폴더는 두 단계 아래까지)의 `rm -r`, 워크트리의 기록이 든 git 관리 폴더(.git/worktrees/<이름>)의
  `rm -r`. `$HOME`, 글롭, 중괄호도 펼쳐 본다. 지금 세션이 그 작업을 시작했고 dispatch 의 워커가 아니면(nonstop, 사용자가
  이 세션에서 맡긴 job) 막지 않는다. 병합되지 않은 작업(닫힌 PR)과 job 기록이 없는 워크트리도 막지 않는다.
  브랜치 지우기(git branch -D, git push --delete)는 보지 않는다. 워크트리에 체크아웃된 브랜치는 git 이 지우지 않고,
  워크트리를 지키면 리드가 볼 기록이 남기 때문이다.

「지금 세션이 그 작업을 시작했는가」는 세션 기록(본체와 하위 에이전트)의 Bash 호출에서 그 워크트리에서 돈
`job.py start` 를 찾아 가른다. dispatch 의 워커는 첫 지시문(메타 줄을 건너뛴 첫 사용자 글)이 「fade:job 스킬로 아래
계획서를 수행한다」로 시작한다. 명령 해석은 병합 훅과 같다(merge_gate.located). 세션 기록이 없으면 가를 수 없어 막지 않는다.
폴더를 알 수 없는 start(셸 변수로 cd)를 그 작업이 시작되기 전 하루 안에 냈으면, 리드만 할 명령은 이 세션이 시작한
것으로 보고 막고, 지우기는 리드의 기록을 요구한다(둘 다 막는 쪽).
못 막는 것: 환경이 세션을 닫으면서 워크트리까지 지우는 것(Bash 가 아닌 도구), 그 세션이 띄운 다른 세션(claude -p)의 명령,
bash -c·eval·셸 변수에 담은 호출, 셸 변수로 가리킨 워크트리 지우기, fade-job.json 을 직접 고치는 것(contrasted 와
hardened 는 워커가 쓰는 같은 기록에 있고, 워크트리를 지우면 함께 사라진다), 같은 워크트리에 다시 띄운 워커가 그 세션에서
start 를 하지 않은 경우, 리드가 병합하고 `job.py merged` 를 남기지 않은 작업(병합되지 않은 작업으로 보인다).
이 훅이 오류로 죽으면 판정하지 않는다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402
from merge_gate import job  # noqa: E402

LEAD_ONLY = ("human-done", "contrasted", "hardened", "resume")
DISPATCHED = "fade:job 스킬로 아래 계획서를 수행한다"  # dispatch 가 워커에 주는 첫 지시문의 머리


def pieces_of(content):
    """사용자 글의 글 조각들. 앱이나 훅이 넣은 메타 글(< 로 시작)은 부르는 쪽이 거른다."""
    return [content] if isinstance(content, str) else [
        c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]


def bash_calls(transcript):
    """세션 기록(본체와 하위 에이전트)의 (호출 때의 세션 폴더, Bash 명령)들과 첫 사용자 글.
    첫 사용자 글은 메타 줄(앱이나 훅이 넣은 것)을 건너뛴 사람이나 리드의 첫 지시문이다."""
    calls, first = [], None
    for path in merge_gate.transcript_files(transcript):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                content = (row.get("message") or {}).get("content")
                if path == transcript and first is None and row.get("type") == "user" and content \
                        and not row.get("isMeta"):
                    first = " ".join(t for t in pieces_of(content) if not t.lstrip().startswith("<")) or None
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                        calls.append((row.get("cwd"), (part.get("input") or {}).get("command") or "",
                                      merge_gate.seconds(row.get("timestamp"))))
    return calls, first or ""


def started_here(calls, wt, started):
    """세션 기록의 Bash 호출 가운데 그 워크트리에서 돈 `job.py start` 가 있으면 True. 폴더를 알 수 없는
    (셸 변수로 cd 한) start 를 그 작업이 시작되기 전 하루 안(앞 명령이나 승인 대기로 벌어질 수 있다)이나 1분 뒤까지에
    냈으면 None(그럴 수 있음), 없으면 False. 기록의 시각은 명령을 낸 때이고 started 는 job.py 가 돈 때다."""
    maybe = False
    for cwd, command, at in calls:
        try:
            pieces = merge_gate.located(command, cwd)
        except ValueError:
            continue
        for here, seg in pieces:
            if merge_gate.job_command(seg) != "start":
                continue
            if here is None:
                maybe = maybe or (at is not None and -60 <= (started or 0) - at <= 86400)
            elif os.path.isdir(here) and job.git_dir(here) and job.top_dir(here) == wt:
                return True
    return None if maybe else False


def admin_worktree(folder):
    """git 관리 폴더(.git/worktrees/<이름>)면 그 gitdir 이 가리키는 워크트리. 아니면 None."""
    try:
        with open(os.path.join(folder, "gitdir"), encoding="utf-8") as f:
            # --relative-paths 로 만든 워크트리는 gitdir 이 관리 폴더 기준의 상대 경로다
            return os.path.dirname(os.path.realpath(os.path.join(folder, f.read().strip())))
    except OSError:
        return None


def worktrees_under(path):
    """path 를 지우면 사라지는 job 기록이 든 워크트리들의 (기록, 워크트리): path 가 워크트리의 맨 위 폴더, 그런 워크트리를
    담은 폴더, 워크트리의 기록이 든 git 관리 폴더일 때다. 워크트리 안의 파일이나 하위 폴더는 치지 않는다."""
    if not path or not os.path.isdir(path):
        return []
    real = os.path.realpath(path)
    found = set()
    # git 관리 폴더: .git/worktrees/<이름>, .git/worktrees, .git
    for admin in ([real] + glob.glob(os.path.join(real, "*")) + glob.glob(os.path.join(real, "worktrees", "*"))
                  + glob.glob(os.path.join(real, ".git", "worktrees", "*"))):  # 메인 체크아웃째 지우면 그 관리 폴더도 사라진다
        wt = admin_worktree(admin)
        if wt:
            found.add(wt)
    if job.git_dir(real):
        for line in merge_gate.git_out(real, "worktree", "list", "--porcelain").splitlines():
            wt = os.path.realpath(line[len("worktree "):]) if line.startswith("worktree ") else None
            if wt and (wt == real or wt.startswith(real.rstrip("/") + "/")):
                found.add(wt)
    else:  # git 아닌 폴더: 두 단계 아래까지의 워크트리(.git 이 파일)와 레포(.git 이 폴더. 그 레포의 워크트리 모두)
        for marker in glob.glob(os.path.join(real, "*", ".git")) + glob.glob(os.path.join(real, "*", "*", ".git")):
            if os.path.isfile(marker):
                found.add(os.path.dirname(marker))
            elif os.path.isdir(marker):
                for line in merge_gate.git_out(os.path.dirname(marker), "worktree", "list", "--porcelain").splitlines():
                    if line.startswith("worktree "):
                        found.add(os.path.realpath(line[len("worktree "):]))
    out = []
    for wt in sorted(found):
        state = job.load(wt) if os.path.isdir(wt) and job.git_dir(wt) else None
        if state:
            out.append((state, wt))
    return out


def expanded(here, target):
    """rm 의 대상 하나를 셸처럼 펼친 경로들: 홈($HOME, ~), 중괄호({a,b}), 글롭(*, ?, [...]). 끝 이름이 글롭뿐이면
    (dir/*, dir/.*) 그 폴더째로 보고, 이름이 붙은 글롭은 맞는 것들로 펼친다(맞는 것이 없으면 지우는 것이 없다)."""
    target = merge_gate.expand_home(target, cwd=here)
    if here is None and not os.path.isabs(target):
        return []
    m = re.search(r"\{([^{}]*,[^{}]*)\}", target)
    if m:
        return [p for alt in m.group(1).split(",")
                for p in expanded(here, target[:m.start()] + alt + target[m.end():])]
    path = os.path.normpath(os.path.join(here or "/", target))
    base = os.path.basename(path)
    if any(c in base for c in "*?[") and not any(c.isalnum() for c in base):
        return [os.path.dirname(path)]  # 끝 이름이 글롭뿐이면(*, .*) 그 폴더 안 전부라 그 폴더째로 본다
    return sorted(glob.glob(path)) if any(c in path for c in "*?[") else [path]


def removed(here, seg):
    """조각이 지우는 경로들: `git worktree remove <경로>` 와 재귀 `rm` 의 대상. 끝 이름이 글롭뿐이면(`*`) 그 폴더다."""
    name = os.path.basename(seg[0])
    rest = seg[1:]
    if name == "git":
        while rest and rest[0].startswith("-"):
            rest = rest[1:]  # git --no-pager 같은 옵션. 값이 붙는 것(-C)은 located 가 뗐다
    if name == "git" and rest[:2] == ["worktree", "remove"]:
        targets = [a for a in rest[2:] if not a.startswith("-")]
    elif name == "rm" and any(a == "--recursive" or (a.startswith("-") and not a.startswith("--") and
                                                     ("r" in a or "R" in a)) for a in rest):
        targets = [a for a in rest if not a.startswith("-")]
    else:
        return []
    return [p for t in targets for p in expanded(here, t)]


def problem(command, cwd, transcript):
    """막을 이유. 없으면 None. 막을 조각(리드만 할 job.py 명령, 지우기)이 없으면 세션 기록을 읽지 않는다.
    모든 Bash 호출에 걸리는 훅이라서다."""
    lead_only, wiped = [], []
    for here, seg in merge_gate.located(command, cwd):
        if merge_gate.job_command(seg) in LEAD_ONLY:
            lead_only.append((here, seg))
        # 지우는 경로 가운데 병합된 작업의 워크트리가 있을 때만 세션 기록을 읽는다(rm -rf build 에는 읽지 않는다)
        wiped += [(state, wt) for path in removed(here, seg) for state, wt in worktrees_under(path) if state.get("merged")]
    if not (lead_only or wiped) or not transcript or not os.path.isfile(transcript):
        return None  # 세션 기록이 없으면 누가 시작했는지 가를 수 없다
    calls, first = bash_calls(transcript)
    worker = first.lstrip().startswith(DISPATCHED)  # dispatch 가 띄운 워커. 사람이 있어도 리드의 일을 스스로 하지 않는다
    for here, seg in lead_only:
        found = merge_gate.job_at(here or cwd, merged_too=True)
        # 셸 변수 폴더의 start 처럼 가를 수 없으면 이 세션이 시작한 것으로 본다(막는 쪽)
        if found and (found[0].get("unattended") or worker) and \
                started_here(calls, job.top_dir(found[1]), found[0].get("started")) is not False:
            return ("사람 없는 작업이나 dispatch 의 워커를 돈 세션은 그 작업의 `job.py %s` 를 스스로 남기지 못한다. "
                    "사람이 볼 것은 사람이 확인한 뒤 사람(터미널)이나 사람이 맡긴 리드 세션이 풀고, 대조와 hardener 는 "
                    "리드가 남긴다. 지금 할 수 없으면 보고에 남겨 사람에게 넘긴다" % merge_gate.job_command(seg))
    for state, wt in wiped:
        if started_here(calls, wt, state.get("started")) is True and not worker:
            continue  # 이 세션이 시작한 작업의 정리(nonstop, 이 세션에서 맡긴 job)
        left = [label for c, label in (("contrasted", "리드의 대조(`job.py contrasted \"<대조 결과>\"`)"),
                                       ("hardened", "hardener 결과(`job.py hardened \"<결과>\"`)")) if not state.get(c)]
        if left:
            return ("병합된 워커의 워크트리(%s)를 지우기 전에 리드가 남길 기록이 없다: %s. 리드가 워커의 기록을 "
                    "완료 기준과 대조하고 hardener 를 돌린 뒤, 그 워크트리에서 남기고 지운다. 워커는 자기 워크트리를 "
                    "지우지 않는다" % (wt, ", ".join(left)))
    return None


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    reason = problem((data.get("tool_input") or {}).get("command") or "", data.get("cwd") or os.getcwd(),
                     data.get("transcript_path"))
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade lead_gate: %s" % e, file=sys.stderr)
