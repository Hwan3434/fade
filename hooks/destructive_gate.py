#!/usr/bin/env python3
"""되돌릴 수 없는 명령 몇 가지를 모든 세션에서 막는다.

fade 를 깐 모든 세션의 Bash 호출에 걸린다. job 기록과 상관없다. 막기만 하고 허용은 하지 않는다.
막는 것: 루트, 홈과 그 위 폴더, ~/.ssh 의 재귀 삭제, 기본 브랜치로의 force push, 장치에 쓰는 dd, mkfs.
명령 해석은 병합 훅과 같다. 인용된 글자와 heredoc 본문은 명령으로 치지 않는다.
이 훅이 오류로 죽으면 판정하지 않고 평소 권한 흐름으로 넘긴다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402

SAFE_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr"}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}


def resolve(arg, cwd, home):
    """rm 인자를 셸이 펼칠 절대 경로로 바꾼다. `*` 와 끝의 `/*` 는 그 폴더 전체로 본다."""
    for var in ("${HOME}", "$HOME", "~"):
        if arg == var or arg.startswith(var + "/"):
            arg = home + arg[len(var):]
            break
    if arg == "*" or arg.endswith("/*"):
        arg = arg[:-1]
    path = os.path.normpath(os.path.join(cwd, arg))
    return "/" + path.lstrip("/") if path.startswith("//") else path


def wipes_home(path, home):
    """지우면 홈이 사라지는 경로: 루트와 홈의 위 폴더, 홈, ~/.ssh 와 그 아래."""
    ssh = os.path.join(home, ".ssh")
    return path in (home, ssh) or path.startswith(ssh + "/") or home.startswith(path.rstrip("/") + "/")


def rm_problem(args, cwd, home):
    recursive, operands, options = False, [], True
    for a in args:
        if options and a == "--":
            options = False
        elif options and a.startswith("--"):
            recursive = recursive or a == "--recursive"
        elif options and a.startswith("-") and len(a) > 1:
            recursive = recursive or "r" in a or "R" in a
        else:
            operands.append(a)
    if not recursive:
        return None  # 재귀가 없으면 rm 은 폴더를 지우지 않는다
    hits = [a for a in operands if wipes_home(resolve(a, cwd, home), home)]
    return "%s 의 재귀 삭제" % hits[0] if hits else None


def git_out(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def destination(refspec, cwd):
    src, _, dst = refspec.lstrip("+").partition(":")
    dst = dst or src
    if dst == "HEAD":
        dst = git_out(cwd, "branch", "--show-current")
    return dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst


def push_problem(args, cwd):
    """`git` 뒤의 인자에서 기본 브랜치로 가는 force push 를 찾는다. force 일 때만 로컬 git 을 부른다."""
    args = list(args)
    while args and args[0].startswith("-"):
        a = args.pop(0)
        if a in GIT_VALUE_OPTIONS and args:
            value = args.pop(0)
            if a == "-C":
                cwd = os.path.join(cwd, os.path.expanduser(value))
    if not args or args[0] != "push":
        return None
    force, positional, rest = False, [], args[1:]
    while rest:
        a = rest.pop(0)
        if a in PUSH_VALUE_OPTIONS:
            rest = rest[1:]
        elif a == "--force" or a.startswith("--force-with-lease"):
            force = True
        elif a.startswith("--"):
            continue
        elif a.startswith("-") and len(a) > 1:
            force = force or "f" in a
        else:
            positional.append(a)
    refspecs = positional[1:]
    forced = (refspecs or ["HEAD"]) if force else [r for r in refspecs if r.startswith("+")]
    if not forced:
        return None
    remote = positional[0] if positional else "origin"
    protected = {"main", "master"}
    default = git_out(cwd, "symbolic-ref", "--short", "refs/remotes/%s/HEAD" % remote)
    if default.startswith(remote + "/"):
        protected.add(default[len(remote) + 1:])
    for r in forced:
        dst = destination(r, cwd)
        if dst in protected:
            return "기본 브랜치 %s 로의 force push" % dst
    return None


def problem(command, cwd, home):
    """막을 명령이면 (무엇, 그 조각), 아니면 None."""
    for seg in merge_gate.segments(command):
        while seg and seg[0] == "sudo":
            seg = seg[1:]
        if not seg:
            continue
        name, args = os.path.basename(seg[0]), seg[1:]
        found = None
        if name == "rm":
            found = rm_problem(args, cwd, home)
        elif name == "git":
            found = push_problem(args, cwd)
        elif name == "dd":
            found = next(("장치 %s 에 쓰는 dd" % a[3:] for a in args
                          if a.startswith("of=/dev/") and a[3:] not in SAFE_DEVICES), None)
        elif name == "mkfs" or name.startswith("mkfs."):
            found = "%s 로 디스크 포맷" % name
        if found:
            return found, " ".join(seg)
    return None


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command")
    if not command:
        return
    found = problem(command, data.get("cwd") or os.getcwd(), os.path.normpath(os.path.expanduser("~")))
    if not found:
        return
    reason = ("fade 가 되돌릴 수 없는 명령을 막았다: %s (`%s`). 형태를 바꿔 다시 시도하지 않는다. "
              "꼭 필요하면 사용자에게 이유를 말하고, 사용자가 터미널에서 직접 친다." % found)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade destructive_gate: %s" % e, file=sys.stderr)
