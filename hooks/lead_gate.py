#!/usr/bin/env python3
"""사람과 리드만 하는 일을 job 을 돈 세션이 스스로 하지 못하게 한다.

막는 것은 둘이다.
- 사람 없는 작업(`job.py start --unattended`)을 돈 세션이 그 작업의 `job.py human-done`(사람이 볼 것 풀기),
  `contrasted`(리드의 대조), `hardened`(hardener 결과)를 남기는 것. 사람이 볼 것을 그 작업이 스스로 풀면 human 이
  뜻이 없다. 사람이 터미널에서 치거나, 사람이 맡긴 리드(다른 세션)가 한다.
- 병합된 워커의 워크트리를 리드의 대조와 hardener 기록 없이 지우는 것(`git worktree remove`, 워크트리 폴더째의 `rm -r`).
  지금 세션이 그 작업을 시작했고 dispatch 의 워커가 아니면(nonstop, 사용자가 이 세션에서 맡긴 job) 막지 않는다.
  병합되지 않은 작업(닫힌 PR)과 job 기록이 없는 워크트리도 막지 않는다.

「지금 세션이 그 작업을 시작했는가」는 세션 기록(본체와 하위 에이전트)의 Bash 호출에서 그 워크트리에서 돈
`job.py start` 를 찾아 가른다. dispatch 의 워커는 첫 지시문이 「fade:job 스킬로 아래 계획서를 수행한다」로 시작한다.
명령 해석은 병합 훅과 같다(merge_gate.located). 세션 기록이 없으면 가를 수 없어 막지 않는다.
못 막는 것: 환경이 세션을 닫으면서 워크트리까지 지우는 것(Bash 가 아닌 도구), 그 세션이 띄운 다른 세션(claude -p)의 명령,
셸 변수로 가리킨 워크트리. 이 훅이 오류로 죽으면 판정하지 않는다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402
from merge_gate import job  # noqa: E402

LEAD_ONLY = ("human-done", "contrasted", "hardened")
DISPATCHED = "fade:job 스킬로 아래 계획서를 수행한다"  # dispatch 가 워커에 주는 첫 지시문의 머리


def job_command(seg):
    """`job.py <명령> ...`(경로로 부른 것 포함)의 명령 이름. 아니면 None."""
    for i, tok in enumerate(seg[:-1]):
        if os.path.basename(tok) == "job.py":
            return seg[i + 1]
    return None


def bash_calls(transcript):
    """세션 기록(본체와 하위 에이전트)의 (호출 때의 세션 폴더, Bash 명령)들과 첫 사용자 글."""
    files = [transcript] + sorted(glob.glob(os.path.join(transcript[:-len(".jsonl")], "subagents", "*.jsonl")))
    calls, first = [], None
    for path in files:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                content = (row.get("message") or {}).get("content")
                if path == transcript and first is None and row.get("type") == "user" and content:
                    first = content if isinstance(content, str) else " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict))
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") == "tool_use" and part.get("name") == "Bash":
                        calls.append((row.get("cwd"), (part.get("input") or {}).get("command") or ""))
    return calls, first or ""


def started_here(calls, wt):
    """세션 기록의 Bash 호출 가운데 그 워크트리에서 돈 `job.py start` 가 있는가."""
    for cwd, command in calls:
        try:
            pieces = merge_gate.located(command, cwd)
        except ValueError:
            continue
        for here, seg in pieces:
            if job_command(seg) == "start" and here and os.path.isdir(here) and job.git_dir(here) \
                    and job.top_dir(here) == wt:
                return True
    return False


def worktree_root(path):
    """path 가 job 기록이 있는 워크트리의 맨 위 폴더면 (기록, 워크트리), 아니면 None."""
    if not path or not os.path.isdir(path) or not job.git_dir(path):
        return None
    wt = job.top_dir(path)
    if wt != os.path.realpath(path):
        return None  # 워크트리 안의 파일이나 하위 폴더
    state = job.load(path)
    return (state, wt) if state else None


def removed(here, seg):
    """조각이 지우는 경로들: `git worktree remove <경로>` 와 재귀 `rm` 의 대상."""
    name = os.path.basename(seg[0])
    if name == "git" and seg[1:3] == ["worktree", "remove"]:
        targets = [a for a in seg[3:] if not a.startswith("-")]
    elif name == "rm" and any(a == "--recursive" or (a.startswith("-") and not a.startswith("--") and
                                                     ("r" in a or "R" in a)) for a in seg[1:]):
        targets = [a for a in seg[1:] if not a.startswith("-")]
    else:
        return []
    if here is None:
        return [os.path.expanduser(t) for t in targets if os.path.isabs(os.path.expanduser(t))]
    return [os.path.normpath(os.path.join(here, os.path.expanduser(t))) for t in targets]


def problem(command, cwd, transcript):
    """막을 이유. 없으면 None."""
    pieces = merge_gate.located(command, cwd)
    calls, first = bash_calls(transcript) if transcript and os.path.isfile(transcript) else (None, "")
    if calls is None:
        return None  # 세션 기록이 없으면 누가 시작했는지 가를 수 없다
    for here, seg in pieces:
        if job_command(seg) in LEAD_ONLY:
            found = merge_gate.job_at(here or cwd, merged_too=True)
            if found and found[0].get("unattended") and started_here(calls, job.top_dir(found[1])):
                return ("사람 없는 작업을 돈 세션은 그 작업의 `job.py %s` 를 스스로 남기지 못한다. 사람이 볼 것은 사람이 "
                        "확인한 뒤 사람(터미널)이나 사람이 맡긴 리드 세션이 풀고, 대조와 hardener 는 리드가 남긴다. "
                        "지금 할 수 없으면 보고에 남겨 사람에게 넘긴다" % job_command(seg))
        for path in removed(here, seg):
            found = worktree_root(path)
            if not found or not found[0].get("merged"):
                continue
            state, wt = found
            if started_here(calls, wt) and DISPATCHED not in first:
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
