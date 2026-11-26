#!/usr/bin/env python3
"""gh pr merge 직전에 job 기록, CI, PR 의 최신 커밋을 본다. 막으면 실수 기록에 한 줄 남긴다.

job 기록이 있는 워크트리에서만 판정한다. 기록이 없는 곳이나 이 훅이 오류로 죽은 경우에는
아무 판정도 내지 않고 Claude 의 평소 권한 흐름으로 넘긴다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "job"))
import job  # noqa: E402

PUNCTUATION = ";&|()<>\n"
CONTROL = set(";&|()\n")  # 명령을 나누는 글자. < > 는 리다이렉트라 나누지 않는다
HEREDOC = re.compile(r"(?<!<)<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")


def without_heredoc_bodies(command):
    """heredoc 본문 줄을 뺀다. 줄마다 명령으로 읽으니, 파일에 쓰는 글이 명령으로 읽히지 않게 한다."""
    out, end = [], None
    for line in command.replace("\\\n", " ").split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
    return "\n".join(out)


def segments(command):
    """명령 줄을 실제로 실행될 단순 명령 조각(토큰 목록)들로 나눈다. 앞에 붙은 환경 변수 지정은 뗀다.
    인용된 글자와 heredoc 본문은 명령으로 치지 않는다. 해석하지 못하면 ValueError."""
    lex = shlex.shlex(without_heredoc_bodies(command), posix=True, punctuation_chars=PUNCTUATION)
    lex.whitespace_split = True
    lex.whitespace = " \t\r"  # 줄바꿈은 명령을 나누는 글자로 읽는다
    segment, found = [], []
    for tok in list(lex) + [";"]:
        if tok and set(tok) <= CONTROL:
            while segment and "=" in segment[0] and not segment[0].startswith("-"):
                segment = segment[1:]
            if segment:
                found.append(segment)
            segment = []
        else:
            segment.append(tok)
    return found


def merge_segments(command):
    """명령 줄에서 실제로 실행될 `gh pr merge ...` 조각들의 인자를 돌려준다."""
    return [seg[3:] for seg in segments(command)
            if len(seg) >= 3 and os.path.basename(seg[0]) == "gh" and seg[1:3] == ["pr", "merge"]]


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


def head_problem(cwd, merge_args):
    """PR 의 최신 커밋이 검증한 로컬 HEAD 와 다르면 그 이유. gh 가 오류로 끝나거나 값을 못 읽으면 None."""
    target, repo = pr_target(merge_args)
    try:
        r = subprocess.run(["gh", "pr", "view", *target, *repo, "--json", "headRefOid", "-q", ".headRefOid"],
                           cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    remote, local = r.stdout.strip(), job.head(cwd)
    if r.returncode != 0 or not remote or remote == local:
        return None
    return ("PR 의 최신 커밋(%s)이 검증한 로컬 HEAD(%s)와 다르다. push 하지 않은 커밋이 있거나 PR 에 다른 커밋이 올라왔다. "
            "맞춘 뒤 그 커밋에서 다시 검증하고 병합한다" % (job.short(remote), job.short(local)))


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    merges = merge_segments(data.get("tool_input", {}).get("command", ""))
    if not merges:
        return
    cwd = data.get("cwd") or os.getcwd()
    state = job.load(cwd)
    if state is None or state["merged"] or state.get("branch") != job.branch(cwd):
        return
    left = job.missing(state, cwd)
    for problem in (ci_problem(cwd, merges[0]), head_problem(cwd, merges[0])):
        if problem:
            left.append(problem)
    if not left:
        return
    reason = "fade job 의 병합 조건이 채워지지 않았다.\n" + "\n".join("- " + m for m in left) + \
             "\n`job.py show` 로 기록을 보고 채운 뒤 다시 병합한다. 채울 수 없으면 병합하지 않고 보고한다."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False), flush=True)
    job.add_mistake(cwd, state, "gate", "병합하려 했으나 막힘: " + "; ".join(left))  # 판정을 먼저 내보내 기록이 실패해도 막는다


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade merge_gate: %s" % e, file=sys.stderr)
