#!/usr/bin/env python3
"""gh pr merge 직전에 job 기록과 CI 를 본다.

job 기록이 있는 워크트리에서만 판정한다. 기록이 없는 곳이나 이 훅이 오류로 죽은 경우에는
아무 판정도 내지 않고 Claude 의 평소 권한 흐름으로 넘긴다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "job"))
import job  # noqa: E402

CONTROL = set(";&|()")


def merge_segments(command):
    """명령 줄에서 실제로 실행될 `gh pr merge ...` 조각들을 돌려준다. 인용된 글자는 명령으로 치지 않는다."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    segment, segments = [], []
    for tok in lex:
        if tok and set(tok) <= CONTROL:
            segments.append(segment)
            segment = []
        else:
            segment.append(tok)
    segments.append(segment)
    found = []
    for seg in segments:
        while seg and "=" in seg[0] and not seg[0].startswith("-"):
            seg = seg[1:]  # 앞에 붙은 환경 변수 지정
        if len(seg) >= 3 and os.path.basename(seg[0]) == "gh" and seg[1:3] == ["pr", "merge"]:
            found.append(seg[3:])
    return found


VALUE_FLAGS = {"-R", "--repo", "-t", "--subject", "-b", "--body", "-F", "--body-file",
               "-A", "--author-email", "--match-head-commit"}


def pr_target(merge_args):
    """`gh pr merge` 의 인자에서 (PR 지정, 저장소 지정)을 뽑는다. 값이 붙는 옵션의 값은 PR 로 치지 않는다."""
    target, repo, args = [], [], list(merge_args)
    while args:
        a = args.pop(0)
        if a in VALUE_FLAGS:
            value = args.pop(0) if args else ""
            if a in ("-R", "--repo"):
                repo = [a, value]
        elif not a.startswith("-") and not target:
            target = [a]
    return target, repo


def ci_problem(cwd, merge_args):
    """CI 가 아직 돌거나 실패했으면 그 이유. 통과했거나 CI 가 없거나 읽지 못하면 None."""
    target, repo = pr_target(merge_args)
    try:
        r = subprocess.run(["gh", "pr", "checks", *target, *repo], cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode == 0:
        return None
    if r.returncode == 8:
        return "CI 가 아직 돌고 있다. 끝난 뒤 병합한다"
    if not r.stdout.strip():
        return None  # 검사 줄이 없다: CI 가 없거나(no checks reported) gh 가 PR 을 못 찾은 오류
    return "CI 가 실패했다. 원인을 고친 뒤 병합한다\n" + "\n".join(r.stdout.splitlines()[-10:])


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    segments = merge_segments(data.get("tool_input", {}).get("command", ""))
    if not segments:
        return
    cwd = data.get("cwd") or os.getcwd()
    state = job.load(cwd)
    if state is None or state["merged"] or state.get("branch") != job.branch(cwd):
        return
    left = job.missing(state)
    problem = ci_problem(cwd, segments[0])
    if problem:
        left.append(problem)
    if not left:
        return
    reason = "fade job 의 병합 조건이 채워지지 않았다.\n" + "\n".join("- " + m for m in left) + \
             "\n`job.py show` 로 기록을 보고 채운 뒤 다시 병합한다. 채울 수 없으면 병합하지 않고 보고한다."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade merge_gate: %s" % e, file=sys.stderr)
