#!/usr/bin/env python3
"""`job.py review` 직전에 버그 축 리뷰(code-review)가 실제로 diff 를 읽었는지 세션 기록에서 본다.

「읽었다」는 도구 이름이 아니라 내용으로 판정한다. 받은 앞 리뷰(없으면 작업 시작) 뒤의 세션 기록 파일들(본체와
하위 에이전트) 가운데 code-review 의 지시문이 나온 파일에서, 그 뒤에 받은 도구 출력에 `job.py review-files` 가 쓴
`.fade-review/bug.patch` 의 줄이 모두 들어 있어야 한다. cat, Read, git diff, 나눠 읽기 어느 것이든 같다. Read 의 줄
번호 머리는 떼고 견준다. 잘린 출력(토큰 한도, head)은 앞부분 줄만 들어 있어 나머지를 읽은 것으로 치지 않는다.
같은 파일이어야 하는 것은 명세 리뷰어(다른 하위 에이전트)가 읽은 것을 버그 축의 증거로 치지 않기 위해서다.
막으면 보이지 않은 줄 범위를 알리고 실수 기록에 한 줄 남긴다.
판정할 수 없으면(세션 기록이 없거나 못 읽음, bug.patch 가 없음, OS 임시 폴더 레포, 훅이 죽음) 막지 않되, 그 사실과
이유를 에이전트(additionalContext)와 사용자(systemMessage)에게 알린다. 실수를 막는 난간이지 보안 경계가 아니다.
"""
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402
from merge_gate import job  # noqa: E402

MARKER = "## Phase 0 — Gather the diff"  # code-review 지시문의 머리. 앱은 본체 기록에, CLI 는 하위 에이전트 기록에 남긴다
READ_PREFIX = re.compile(r"^ *\d+\t")  # Read 결과 줄의 번호 머리(cat -n 꼴)
SLASH = "<command-name>/code-review</command-name>"  # 사용자가 /code-review 로 부른 흔적


def calls_review(part):
    """code-review 를 부른 흔적인가: Skill 도구 호출이나 사용자의 /code-review."""
    if part["type"] == "tool_use":
        skill = (part.get("input") or {}).get("skill") or "" if part.get("name") == "Skill" else ""
        return skill == "code-review" or skill.endswith(":code-review")
    return part["type"] == "text" and SLASH in (part.get("text") or "")


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
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def output_lines(part):
    """도구 출력의 줄들. Read 의 줄 번호 머리(「12\t」)를 뗀 줄과 그대로의 줄을 둘 다 넣는다
    (숫자와 탭으로 시작하는 diff 줄이 cat 이나 git diff 출력에서 떼여 맞지 않게 되지 않도록)."""
    out = set()
    for line in result_text(part).splitlines():
        out.add(line.rstrip())
        out.add(READ_PREFIX.sub("", line).rstrip())
    return out


def seen_in(path, since):
    """이 기록 파일에서 code-review 지시문 뒤에 받은 도구 출력의 줄들(지시문이 없으면 None)과, code-review 를 부른 흔적이
    있는가."""
    seen, called = None, False
    for part in rows(path, since):
        called = called or calls_review(part)
        if part["type"] == "text" and MARKER in (part.get("text") or ""):
            seen = set()  # 다시 지시문이 나오면 그 뒤의 리뷰만 본다
        elif seen is not None and part["type"] == "tool_result" and not part.get("is_error"):
            seen |= output_lines(part)
    return seen, called


def spans(numbers):
    """줄 번호들을 「a-b」 범위 글로 묶는다."""
    out, start, prev = [], None, None
    for n in numbers:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append((start, prev))
            start = prev = n
    if start is not None:
        out.append((start, prev))
    return ", ".join("%d" % a if a == b else "%d-%d" % (a, b) for a, b in out)


class Unjudged(Exception):
    """판정할 수 없다. 막지 않고 이유를 알린다."""


def review_problem(state, wt, transcript):
    """버그 축이 diff 를 다 읽지 않았으면 막는 이유, 다 읽었으면 None. 판정할 수 없으면 Unjudged."""
    if not transcript:
        raise Unjudged("세션 기록 경로를 받지 못했다(세션 기록을 남기지 않는 실행)")
    if not os.path.isfile(transcript):
        raise Unjudged("세션 기록 파일이 없다: " + transcript)
    made = state.get("review_files") or {}
    if made.get("head") != job.head(wt):
        return ("bug.patch 가 이 커밋(%s)에서 만든 것이 아니다. `job.py review-files <base>` 로 다시 만들고, code-review 로 "
                "`.fade-review/bug.patch` 를 끝까지 읽은 뒤 남긴다" % job.short(job.head(wt)))
    patch = os.path.join(job.top_dir(wt), ".fade-review", "bug.patch")
    if not os.path.isfile(patch):
        raise Unjudged("bug.patch 가 없다. review-files 를 돌린 job.py 가 이 훅과 다른 판일 수 있다(PATH 의 job.py)")
    with open(patch, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    wanted = {i + 1: line.rstrip() for i, line in enumerate(lines) if len(line.strip()) >= 2}
    previous = state.get("review") or {}
    since = previous.get("at") or state.get("started") or 0
    files = [transcript] + sorted(glob.glob(os.path.join(transcript[:-len(".jsonl")], "subagents", "*.jsonl")))
    best, reviewed, called = None, False, False
    for f in files:
        seen, call = seen_in(f, since)
        called = called or call
        if seen is None:
            continue
        reviewed = True
        missing = [n for n, text in wanted.items() if text not in seen]
        if not missing:
            return None
        best = missing if best is None or len(missing) < len(best) else best
    after = "앞 리뷰" if previous else "작업 시작"
    if not reviewed and called:
        raise Unjudged("code-review 를 부른 흔적은 있는데 그 지시문의 머리 글(%s)을 찾지 못했다. code-review 스킬의 글이 "
                       "바뀌었을 수 있다. fade 의 review_gate.py 의 MARKER 를 맞춰야 한다" % MARKER)
    if not reviewed:
        return ("%s 뒤의 세션 기록에 code-review 가 돈 흔적이 없다. code-review 를 수준과 대상을 적어 부르고"
                "(`medium .fade-review/bug.patch`), 그 리뷰가 bug.patch 를 끝까지 읽은 뒤 남긴다" % after)
    return ("버그 축 리뷰가 bug.patch(%d줄)를 다 읽지 않았다. 출력에 보이지 않은 줄: %s. 잘린 출력(토큰 한도, head)은 "
            "앞부분만 읽은 것이다. 보이지 않은 줄을 나눠 읽은 뒤 다시 남긴다. 명세 리뷰어가 읽은 것은 치지 않는다"
            % (len(lines), spans(best)))


def note(reason):
    """막지 않되 판정하지 못한 사실과 이유를 에이전트와 사용자에게 알린다."""
    text = "fade 리뷰 훅이 판정하지 못했다. 막지 않는다: " + reason
    print(json.dumps({"systemMessage": text, "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                                    "additionalContext": text}}, ensure_ascii=False))


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return
    cwd = data.get("cwd") or os.getcwd()
    for here, seg in merge_gate.located((data.get("tool_input") or {}).get("command") or "", cwd):
        if not is_review(seg):
            continue
        # 폴더를 알 수 없으면(셸 변수, 없는 폴더) 세션 폴더의 기록으로 판정한다
        found = merge_gate.job_at(here) if here is not None else merge_gate.job_at(cwd)
        if not found:
            continue
        state, wt = found
        if job.under_temp(job.main_checkout(wt)):
            note("레포가 OS 임시 폴더 아래라(써 보기, 테스트) 판정하지 않는다")
            return
        try:
            problem = review_problem(state, wt, data.get("transcript_path"))
        except Unjudged as e:
            note(str(e))
            return
        if not problem:
            continue
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": problem}}, ensure_ascii=False), flush=True)
        try:  # 판정을 먼저 내보냈으니 기록이 실패해도 막는다. 다른 JSON 을 더 찍지 않는다
            job.add_mistake(wt, state, "gate", "리뷰를 남기려 했으나 막힘: " + problem)
        except Exception as e:
            print("fade review_gate: 실수 기록에 쓰지 못했다: %s" % e, file=sys.stderr)
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 막지 않되, 판정하지 못했다고 알린다
        note("훅이 오류로 끝났다(%s: %s)" % (type(e).__name__, e))
