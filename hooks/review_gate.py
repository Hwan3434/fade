#!/usr/bin/env python3
"""`job.py review` 직전에 버그 축 리뷰(code-review)가 실제로 diff 를 읽었는지 세션 기록에서 본다.

받은 앞 리뷰(없으면 작업 시작) 뒤의 세션 기록 파일들(본체와 하위 에이전트) 가운데, code-review 의 지시문이 나온 뒤
같은 파일에서 diff 를 읽은 곳이 있어야 한다. 읽은 것으로 치는 것은 둘이다.
- `job.py review-files` 가 이 커밋에서 쓴 `.fade-review/bug.patch` 를 끝 줄까지 덮은 Read(실패한 것은 빼고).
- 범위를 준 `git diff` 로, 파일을 줄이지 않고(-- 경로, --stat 등) 출력이 잘리지 않은 것. 앞 리뷰가 없으면 base 와의
  전체(`<base>...<브랜치>`)여야 한다.
같은 파일이어야 하는 것은 명세 리뷰어(다른 하위 에이전트)가 읽은 것을 버그 축의 증거로 치지 않기 위해서다.
job 기록이 없는 곳, OS 임시 폴더의 레포(써 보기, 테스트), 세션 기록 경로를 못 받거나 못 읽은 경우, 이 훅이 오류로
죽은 경우에는 판정하지 않는다. 막으면 실수 기록에 한 줄 남긴다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402
from merge_gate import job  # noqa: E402

MARKER = "## Phase 0 — Gather the diff"  # code-review 지시문의 머리. 앱은 본체 기록에, CLI 는 하위 에이전트 기록에 남긴다
READ_LIMIT = 2000  # Read 도구가 limit 없이 한 번에 읽는 줄 수
SHORTENING = {"--stat", "--numstat", "--shortstat", "--name-only", "--name-status", "--dirstat", "--summary"}
TRUNCATED = ("Output too large", "<persisted-output>")


def is_review(seg):
    """`job.py review ...`(경로로 부른 것 포함)인가. review-files 는 아니다."""
    for i, tok in enumerate(seg[:-1]):
        if os.path.basename(tok) == "job.py":
            return seg[i + 1] == "review"
    return False


def seconds(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def rows(path, since):
    """기록 파일에서 since 뒤의 (종류, 내용) 들. 종류는 text, tool_use, tool_result."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            at = seconds(row.get("timestamp"))
            content = (row.get("message") or {}).get("content")
            if at is None or at <= since or not content:
                continue
            for part in [{"type": "text", "text": content}] if isinstance(content, str) else content:
                if isinstance(part, dict) and part.get("type") in ("text", "tool_use", "tool_result"):
                    out.append(part)
    return out


def result_text(part):
    content = part.get("content")
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def whole_git_diff(command, cwd, first):
    """범위를 주고 파일을 줄이지 않은 git diff 인가. 첫 리뷰면 base 와의 전체(... 범위)여야 한다."""
    for _, seg in merge_gate.located(command, cwd):
        if len(seg) < 2 or os.path.basename(seg[0]) != "git" or seg[1] != "diff":
            continue
        args = seg[2:]
        if "--" in args or SHORTENING & {a.split("=", 1)[0] for a in args}:
            continue
        ranges = [a for a in args if ".." in a and not a.startswith("-")]
        if ranges and (not first or any("..." in r for r in ranges)):
            return True
    return False


def covered(reads, total):
    """Read 들(offset, limit)이 1..total 줄을 모두 덮었는가."""
    spans = sorted((int(o or 1), int(o or 1) + int(n or READ_LIMIT)) for o, n in reads)
    upto = 1
    for start, end in spans:
        if start > upto:
            break
        upto = max(upto, end)
    return upto > total


def evidence(path, since, wt, patch, total, first):
    """이 기록 파일에 code-review 지시문 뒤의 diff 읽기가 있는가."""
    started, calls, reads = False, {}, []
    for part in rows(path, since):
        if part["type"] == "text" and MARKER in (part.get("text") or ""):
            started, calls, reads = True, {}, []
        elif started and part["type"] == "tool_use":
            calls[part.get("id")] = part
        elif started and part["type"] == "tool_result" and not part.get("is_error"):
            call = calls.get(part.get("tool_use_id"))
            if not call:
                continue
            given = call.get("input") or {}
            if call.get("name") == "Read" and os.path.realpath(given.get("file_path", "")) == patch:
                reads.append((given.get("offset"), given.get("limit")))
                if covered(reads, total):
                    return True
            elif call.get("name") == "Bash" and not any(t in result_text(part) for t in TRUNCATED):
                if whole_git_diff(given.get("command") or "", wt, first):
                    return True
    return False


def review_problem(state, wt, transcript):
    """버그 축이 diff 를 읽은 흔적이 없으면 그 이유. 판정할 수 없으면 None."""
    if not transcript or not os.path.isfile(transcript):
        return None
    made = state.get("review_files") or {}
    if made.get("head") != job.head(wt):
        return ("bug.patch 가 이 커밋(%s)에서 만든 것이 아니다. `job.py review-files <base>` 로 다시 만들고, code-review 로 "
                "`.fade-review/bug.patch` 를 끝까지 읽은 뒤 남긴다" % job.short(job.head(wt)))
    previous = state.get("review") or {}
    since = previous.get("at") or state.get("started") or 0
    patch = os.path.realpath(os.path.join(job.top_dir(wt), ".fade-review", "bug.patch"))
    with open(patch, encoding="utf-8", errors="replace") as f:
        total = len(f.read().splitlines())
    files = [transcript] + sorted(glob.glob(os.path.join(transcript[:-len(".jsonl")], "subagents", "*.jsonl")))
    if any(evidence(f, since, wt, patch, total, not previous) for f in files if os.path.isfile(f)):
        return None
    return ("버그 축 리뷰가 diff 를 읽은 기록이 없다(%s 뒤의 세션 기록). code-review 를 수준을 적어 부르고(`medium`), "
            "그 리뷰가 `.fade-review/bug.patch` 를 끝 줄까지 읽은 뒤 남긴다. 명세 리뷰어가 읽은 것, code-review 보다 앞의 "
            "읽기, 잘리거나 파일을 줄인 git diff 는 치지 않는다" % ("앞 리뷰" if previous else "작업 시작"))


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    cwd = data.get("cwd") or os.getcwd()
    for here, seg in merge_gate.located((data.get("tool_input") or {}).get("command") or "", cwd):
        if not is_review(seg):
            continue
        found = merge_gate.job_at(here)
        if not found or job.under_temp(job.main_checkout(found[1])):
            continue
        state, wt = found
        problem = review_problem(state, wt, data.get("transcript_path"))
        if not problem:
            continue
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": problem}}, ensure_ascii=False), flush=True)
        job.add_mistake(wt, state, "gate", "리뷰를 남기려 했으나 막힘: " + problem)  # 판정을 먼저 내보내 기록이 실패해도 막는다
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지도 허용하지도 않는다
        print("fade review_gate: %s" % e, file=sys.stderr)
