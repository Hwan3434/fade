#!/usr/bin/env python3
"""되돌릴 수 없는 명령 몇 가지를 모든 세션에서 막는다.

fade 를 깐 모든 세션의 Bash 호출에 걸린다. job 기록과 상관없다. 막기만 하고 허용은 하지 않는다.
막는 것: 루트, 홈과 그 위 폴더, ~/.ssh 의 재귀 삭제, 기본 브랜치로의 force push, 장치에 쓰는 dd, mkfs.
명령 해석은 병합 훅과 같다. 인용된 글자와 heredoc 본문은 명령으로 치지 않는다.
이 훅이 오류로 죽으면 판정하지 않고 평소 권한 흐름으로 넘긴다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402

SAFE_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr"}
UNKNOWN = "/<알 수 없는 폴더>/x"  # 폴더를 알 수 없을 때 상대 경로를 풀어 볼 자리
PUSH_VALUE_OPTIONS = merge_gate.PUSH_VALUE_OPTIONS
git_out = merge_gate.git_out


def resolve(arg, cwd, home):
    """인자를 셸이 펼칠 절대 경로로 바꾼다. 끝 이름이 글자 없이 글롭뿐이면(`*`, `.*`, `.[!.]*`) 그 폴더 안 전부라
    폴더를 돌려준다. `*.bak` 처럼 이름이 걸린 글롭은 폴더 전체가 아니다."""
    for var in ("${HOME}", "$HOME", "~"):
        if arg == var or arg.startswith(var + "/"):
            arg = home + arg[len(var):]
            break
    path = os.path.normpath(os.path.join(cwd, arg))
    if path.startswith("//"):
        path = "/" + path.lstrip("/")
    base = os.path.basename(path)
    whole = any(ch in base for ch in "*?[") and not any(ch.isalnum() for ch in base)
    return os.path.dirname(path) if whole else path


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
    if cwd is None:  # 폴더를 알 수 없다: 그 폴더째나 그 위를 지우는 상대 경로는 홈일 수 있다
        hits = [a for a in operands if wipes_home(resolve(a, UNKNOWN, home), home) or
                wipes_home(resolve(a, UNKNOWN, home), UNKNOWN)]
    else:
        hits = [a for a in operands if wipes_home(resolve(a, cwd, home), home)]
    return "%s 의 재귀 삭제" % hits[0] if hits else None


def destination(refspec, cwd):
    src, _, dst = refspec.lstrip("+").partition(":")
    dst = dst or src
    if dst == "HEAD":
        dst = git_out(cwd, "branch", "--show-current")
    return dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst


def push_problem(args, cwd):
    """`git` 뒤의 인자에서 기본 브랜치로 가는 force push 를 찾는다. force 일 때만 로컬 git 을 부른다."""
    args = list(args)  # git -C 와 값이 붙는 git 옵션은 located 가 이미 뗐다
    while args and args[0].startswith("-"):
        args.pop(0)
    if not args or args[0] != "push":
        return None
    force, every, positional, rest = False, False, [], args[1:]
    while rest:
        a = rest.pop(0)
        if a == "--mirror":
            force = every = True  # mirror 는 옵션 없이도 모든 브랜치를 강제로 맞춘다
        elif a in ("--all", "--branches"):
            every = True
        elif a in PUSH_VALUE_OPTIONS:
            rest = rest[1:]
        elif a == "--force" or a.startswith("--force-with-lease"):
            force = True
        elif a.startswith("--"):
            continue
        elif a.startswith("-") and len(a) > 1:
            force = force or "f" in a
        else:
            positional.append(a)
    if force and every:
        return "기본 브랜치를 포함한 모든 브랜치의 force push"
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
    """막을 명령이면 (무엇, 그 조각), 아니면 None. 명령 해석(cd 따라가기, git -C, 리다이렉트 떼기)은 병합 훅의
    located 를 그대로 쓴다. 폴더를 알 수 없는 조각(셸 변수, 없는 폴더로의 cd 뒤)의 상대 경로는 그 폴더째나 그 위를
    지우는 것(`.`, `*`, `..`)이면 막는다. 비어 있는 셸 변수로 cd 하면 홈으로 가고, 없는 폴더로의 cd 가 실패하면
    `;` 뒤의 rm 은 앞 폴더에서 돌아, 그 폴더가 홈일 수 있어서다."""
    for here, seg in merge_gate.located(command, cwd):
        name, args = os.path.basename(seg[0]), seg[1:]
        found = None
        if name == "rm":
            found = rm_problem(args, here, home)
        elif name == "git":
            found = push_problem(args, here or cwd)
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
