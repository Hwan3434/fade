#!/usr/bin/env python3
"""base 로 들어가는 병합 직전에 job 기록을 본다. 막으면 실수 기록에 한 줄 남긴다.

보는 병합은 셋이다. `gh pr merge`(CI 와 PR 의 최신 커밋도 본다), base 를 체크아웃한 곳에서 작업 브랜치를 합치는
`git merge`, 작업 브랜치를 base 로 보내는 `git push <원격> <src>:<base>`. 작업 브랜치에서 base 를 합치는 `git merge` 는
보지 않는다(충돌 풀기). 기록은 세션의 현재 폴더만이 아니라 명령이 가리키는 폴더(같은 명령 줄의 cd, git -C)와
병합하는 브랜치가 체크아웃된 워크트리에서 찾는다. gh pr merge 는 PR 의 브랜치(headRefName)로 워크트리를 찾는다.
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
# heredoc 의 끝 글. 따옴표를 쳤으면 따옴표 안 전부(END-NOTES, A.B), 아니면 연산자와 따옴표가 아닌 글자들이다
# 따옴표 없는 끝 글은 글자나 _ 로 시작해야 한다. $((1<<2)) 의 2 를 끝 글로 읽으면 뒤 줄이 모두 본문으로 사라진다
HEREDOC = re.compile(r"(?<!<)<<-?\s*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([A-Za-z_][^\s;&|<>()'\"]*))")
ARITH = re.compile(r"\$?\(\([^()]*\)\)")
QUOTED = ";&|()<>\n"  # 따옴표 안이나 \ 뒤에 있으면 글자일 뿐인 연산자 글자
HIDE = {ord(c): 0xE000 + i for i, c in enumerate(QUOTED)}  # 해석하는 동안 쓰는 사용 영역 글자
SHOW = {v: k for k, v in HIDE.items()}


def without_heredoc_bodies(command):
    """heredoc 본문 줄을 뺀다. 줄마다 명령으로 읽으니, 파일에 쓰는 글이 명령으로 읽히지 않게 한다."""
    out, end = [], None
    for line in command.replace("\\\n", " ").split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        # 따옴표 안과 산술($((1<<n)), ((x<<=y)))의 << 는 heredoc 이 아니다
        m = HEREDOC.search(ARITH.sub("", hide_quoted(line)))
        if m:
            end = next(g for g in m.groups() if g is not None)
    return "\n".join(out)


def without_comments(command):
    """따옴표 밖에서 낱말 첫머리의 # 부터 그 줄 끝까지를 뺀다. 줄바꿈은 남겨 다음 줄을 새 명령으로 읽게 한다.
    shlex 의 주석 처리는 줄바꿈까지 먹어 다음 줄을 앞 명령에 붙이고, 낱말 가운데의 # 도 주석으로 읽어 쓰지 않는다."""
    out, quote, prev, i = [], None, "\n", 0
    while i < len(command):
        c = command[i]
        if quote is None and c == "#" and (prev.isspace() or prev in PUNCTUATION):
            end = command.find("\n", i)
            if end < 0:
                break
            i = end
            continue
        if c == "\\" and quote != "'" and i + 1 < len(command):
            out.append(command[i:i + 2])
            prev, i = "\\", i + 2  # 이스케이프한 공백 뒤의 # 는 낱말 가운데다
            continue
        if c in "'\"" and quote in (None, c):
            quote = None if quote else c
        out.append(c)
        prev, i = c, i + 1
    return "".join(out)


def without_ansi_c(command):
    """따옴표 밖에서 시작하는 bash 의 $'...' 를 빈 따옴표로 바꾼다. shlex 가 못 읽는 꼴이라서다. 작은따옴표나
    큰따옴표 안의 $' 와 주석은 그대로 둔다(주석 속 작은따옴표에 따옴표 상태가 흔들리지 않게 주석은 건너뛴다).
    닫히지 않은 $' 는 그대로 둬 shlex 가 해석하지 못했다고 알리게 한다."""
    out, quote, prev, i, n = [], None, "\n", 0, len(command)
    while i < n:
        c = command[i]
        if quote is None and c == "#" and (prev.isspace() or prev in PUNCTUATION):
            end = command.find("\n", i)
            end = n if end < 0 else end
            out.append(command[i:end])
            prev, i = "#", end
            continue
        if quote is None and command.startswith("$'", i):
            j = i + 2
            while j < n and command[j] != "'":
                j += 2 if command[j] == "\\" else 1
            if j < n:
                out.append("''")
                prev, i = "'", j + 1
                continue
        if c == "\\" and quote != "'" and i + 1 < n:
            out.append(command[i:i + 2])
            prev, i = "\\", i + 2
            continue
        if c in "'\"" and quote in (None, c):
            quote = None if quote else c
        out.append(c)
        prev, i = c, i + 1
    return "".join(out)


def hide_quoted(command):
    """따옴표 안과 \\ 뒤의 연산자 글자를 사용 영역 글자로 바꾼다. shlex 는 따옴표를 벗긴 뒤 「">"」와 「>」를 같은 낱말로
    내어, 따옴표로 묶은 글자를 리다이렉트나 명령 구분으로 읽게 된다. segments 가 나눈 뒤 되돌린다."""
    out, quote, i, n = [], None, 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            out.append(c + command[i + 1].translate(HIDE))
            i += 2
            continue
        if c in "'\"" and quote in (None, c):
            quote = None if quote else c
        out.append(c.translate(HIDE) if quote else c)
        i += 1
    return "".join(out)


def segments(command):
    """명령 줄의 단순 명령 조각(토큰 목록)들. joined 에서 잇는 글자를 뺀 것이다."""
    return [seg for seg, _ in joined(command)]


def joined(command):
    """명령 줄을 실제로 실행될 단순 명령 조각(토큰 목록)과 그 뒤를 잇는 글자의 짝들로 나눈다. 앞에 붙은 환경 변수 지정과 리다이렉트(그 대상까지)는
    뗀다. 인용된 글자, heredoc 본문, 주석은 명령으로 치지 않는다. 해석하지 못하면 ValueError.
    shlex 가 못 읽는 bash 의 $'...' 는 빈 따옴표로 바꿔 읽는다. 인용된 글자라 명령으로 치지 않는 것은 같다."""
    # 리다이렉트에 붙은 fd 번호(2>, 1>&2)를 뗀다. shlex 는 「3 >」과 「3>」을 같은 낱말로 나눠, 나눈 뒤에는
    # 띄어 쓴 인자(gh pr merge 3 >/dev/null 의 PR 번호)와 가를 수 없다
    command = re.sub(r"(?<![\w$\"'/.~-])\d+(?=[<>])", "", without_heredoc_bodies(command))
    lex = shlex.shlex(hide_quoted(without_comments(without_ansi_c(command))), posix=True,
                      punctuation_chars=PUNCTUATION)
    lex.whitespace_split = True
    lex.whitespace = " \t\r"  # 줄바꿈은 명령을 나누는 글자로 읽는다
    lex.commenters = ""
    segment, found, skip = [], [], False
    for tok in list(lex) + [";"]:
        if tok and set(tok) <= CONTROL:
            while segment and "=" in segment[0] and not segment[0].startswith("-"):
                segment = segment[1:]
            if segment:
                found.append((segment, tok))  # 조각과 그 뒤를 잇는 글자(&&, ;, ||, 줄바꿈 등)
            segment, skip = [], False
        elif skip:
            skip = False  # 리다이렉트의 대상
        elif tok and set(tok) <= set("<>&"):
            skip = True  # 리다이렉트(>/dev/null, 2>&1, < f). 따옴표로 묶은 글자는 hide_quoted 가 숨겨 여기 오지 않는다
        else:
            segment.append(tok.translate(SHOW))
    return found


GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
MERGE_VALUE_OPTIONS = {"-m", "-F", "-s", "-X", "--strategy", "--strategy-option", "--file"}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "time", "!", "{", "if", "then", "elif", "else", "while", "until", "do"}


def folder(base, value, lexical=False):
    """cd 나 git -C 의 값으로 간 폴더. 셸 변수처럼 펼칠 수 없거나 없는 폴더면 None(알 수 없음)이다.
    lexical 이면 없는 폴더도 글자 그대로의 경로로 푼다(같은 줄에서 mkdir 한 폴더). `$HOME`, `${HOME}` 은 홈으로 펼친다."""
    for var in ("${HOME}", "$HOME"):
        if value == var or value.startswith(var + "/"):
            value = "~" + value[len(var):]
            break
    if "$" in value or "`" in value or (base is None and not os.path.isabs(os.path.expanduser(value))):
        return None
    path = os.path.normpath(os.path.join(base or "/", os.path.expanduser(value)))
    return path if lexical or os.path.isdir(path) else None


def located(command, cwd, lexical=False):
    """명령 줄의 단순 명령 조각마다 (그 조각이 도는 폴더, 토큰들)을 돌려준다. 같은 명령 줄의 cd 를 따라가고,
    git 의 -C 는 그 조각의 폴더로 읽어 토큰에서 뗀다. 셸 예약어, 감싸는 명령, 리다이렉트는 뗀다.
    폴더를 알 수 없으면(셸 변수, 없는 폴더) 그 조각의 폴더는 None 이다. 부르는 쪽이 세션 폴더로 판정한다.
    리다이렉트는 segments 가 이미 뗐다."""
    out = []
    for seg, join in joined(command):
        while seg and (seg[0] in WRAPPERS or ("=" in seg[0] and not seg[0].startswith("-"))):
            seg = seg[1:]
        if not seg:
            continue
        name = os.path.basename(seg[0])
        if name == "cd":
            target = next((a for a in seg[1:] if not a.startswith("-") or a == "-"), "~")
            if target != "-":
                # 없는 폴더를 글자 그대로 푸는 것은 && 로 이을 때뿐이다. cd 가 실패하면 && 뒤는 돌지 않지만,
                # ; || 줄바꿈 뒤는 앞 폴더에서 돈다
                cwd = folder(cwd, target) or (folder(cwd, target, True) if lexical and join == "&&" else None)
            continue
        here = cwd
        if name == "git":
            args, rest = [seg[0]], seg[1:]
            while rest and rest[0].startswith("-"):
                a = rest.pop(0)
                if a in GIT_VALUE_OPTIONS and rest:
                    value = rest.pop(0)
                    if a == "-C":
                        here = folder(here, value, lexical)
                    continue
                args.append(a)
            seg = args + rest
        out.append((here, seg))
    return out


def git_out(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def bases(cwd):
    """base 로 칠 브랜치 이름들: main, master, 그 레포 origin 의 기본 브랜치."""
    names = {"main", "master"}
    default = git_out(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if default.startswith("origin/"):
        names.add(default[len("origin/"):])
    return names


def worktree_of(cwd, branch):
    """cwd 의 레포에서 branch 가 체크아웃된 워크트리 경로. 없으면 None. 원격 추적 이름(origin/x)도 x 로 찾는다."""
    if not branch or not os.path.isdir(cwd):
        return None
    listing = git_out(cwd, "worktree", "list", "--porcelain")
    names = {branch[len(p):] for p in ("refs/heads/", "refs/remotes/origin/", "origin/") if branch.startswith(p)} | {branch}
    path = None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/") and line[len("branch refs/heads/"):] in names:
            return path
    return None


def job_at(cwd, merged_too=False):
    """cwd 의 워크트리에 지금 브랜치의 job 기록이 있으면 (기록, 워크트리), 아니면 None. 병합이 기록된 작업은
    merged_too 일 때만 친다(승인 창 훅은 병합 뒤에도 사람이 없다)."""
    if not cwd or not os.path.isdir(cwd) or not job.git_dir(cwd):
        return None
    state = job.load(cwd)
    if state is None or (state["merged"] and not merged_too) or state.get("branch") != job.branch(cwd):
        return None
    return state, cwd


def git_targets(here, seg):
    """`git merge`·`git push` 조각이 base 로 들이는 작업 브랜치의 job (기록, 워크트리)들."""
    if len(seg) < 2 or os.path.basename(seg[0]) != "git" or seg[1] not in ("merge", "pull", "push"):
        return []
    values = PUSH_VALUE_OPTIONS if seg[1] == "push" else MERGE_VALUE_OPTIONS
    args, rest = [], seg[2:]
    while rest:
        a = rest.pop(0)
        if a in values:
            rest = rest[1:]
        elif not a.startswith("-"):
            args.append(a)
    if seg[1] in ("merge", "pull"):
        if job.branch(here) not in bases(here):
            return []  # 작업 브랜치에서 base 를 합치는 것(충돌 풀기)은 보지 않는다
        # pull 은 첫 인자가 원격이고 그 뒤가 합칠 브랜치다
        found = [job_at(worktree_of(here, b)) for b in (args if seg[1] == "merge" else args[1:])]
    else:
        found = []
        for spec in args[1:]:
            src, _, dst = spec.lstrip("+").partition(":")
            dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
            if dst and dst in bases(here):
                found.append(job_at(here) if src in ("HEAD", "@", job.branch(here)) else job_at(worktree_of(here, src)))
    return [f for f in found if f]


def pr_branch(cwd, merge_args):
    """`gh pr merge` 의 PR 이 올라온 브랜치. 읽지 못하면 빈 글."""
    target, repo = pr_target(merge_args)
    try:
        r = subprocess.run(["gh", "pr", "view", *target, *repo, "--json", "headRefName", "-q", ".headRefName"],
                           cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def gh_target(here, merge_args):
    """`gh pr merge` 가 들이는 작업의 job (기록, 워크트리). PR 의 브랜치가 체크아웃된 워크트리의 기록이 먼저다(다른 작업의
    워크트리에서 합쳐도 그 PR 의 기록을 본다). PR 의 브랜치를 못 읽거나 그 워크트리가 없으면 그 폴더의 기록을 본다."""
    if here is None:
        return None
    return job_at(worktree_of(here, pr_branch(here, merge_args))) or job_at(here)


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


def problems(command, cwd):
    """명령 줄이 base 로 들이는 job 마다 빠진 것을 모은다. (기록, 워크트리, 빠진 것들) 의 목록."""
    out = []
    for here, seg in located(command, cwd):
        try:  # 한 조각의 판정이 실패해도 같은 줄의 다른 병합 판정은 남긴다
            out += judge(here, seg, cwd)
        except Exception as e:
            print("fade merge_gate: %s 조각을 판정하지 못했다: %s" % (" ".join(seg[:3]), e), file=sys.stderr)
    return [o for o in out if o[2]]


def judge(here, seg, cwd):
    """한 조각이 base 로 들이는 job 들의 (기록, 워크트리, 빠진 것들)."""
    if len(seg) >= 3 and os.path.basename(seg[0]) == "gh" and seg[1:3] == ["pr", "merge"]:
        # 폴더를 알 수 없거나(셸 변수, 없는 폴더) 그 폴더에서 기록을 못 찾으면(기록 없는 다른 레포 포함) 세션 폴더의 기록을 본다
        found = gh_target(here, seg[3:]) or (here != cwd and gh_target(cwd, seg[3:]))
        if not found:
            return []
        state, wt = found
        return [(state, wt, job.missing(state, wt) + [p for p in (ci_problem(wt, seg[3:]), head_problem(wt, seg[3:])) if p])]
    if here is None:
        if len(seg) >= 2 and os.path.basename(seg[0]) == "git" and seg[1] == "push":
            here = cwd  # `<src>:<base>` 를 적은 push 는 폴더를 몰라도 base 로 간다. 어느 작업인지는 세션 폴더로 본다
        else:
            return []  # 어느 브랜치에서 도는지 모르니 base 로 들이는지 알 수 없다
    return [(state, wt, job.missing(state, wt)) for state, wt in git_targets(here, seg)]


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    found = problems(data.get("tool_input", {}).get("command", ""), data.get("cwd") or os.getcwd())
    if not found:
        return
    state, cwd, left = found[0]
    reason = "fade job 의 병합 조건이 채워지지 않았다.\n" + "\n".join("- " + m for m in left) + \
             "\n채운 뒤 `job.py check` 로 빠진 것이 없는지 보고 다시 병합한다. 채울 수 없으면 병합하지 않고 보고한다."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False), flush=True)
    job.add_mistake(cwd, state, "gate", "병합하려 했으나 막힘: " + "; ".join(left))  # 판정을 먼저 내보내 기록이 실패해도 막는다


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade merge_gate: %s" % e, file=sys.stderr)
