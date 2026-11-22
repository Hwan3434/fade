#!/usr/bin/env python3
"""nonstop 의 작업 목록과 hook.

작업 목록은 ~/.cache/fade-nonstop/<세션 ID>/tasks.json 한 파일이다.
상태: todo(남음) done(끝남) hold(사용자 답이 필요해 보류) blocked(권한·환경에 막힘)

  nonstop.py init   <세션> <제목>...         작업 목록을 새로 만든다 (남은 작업이 있는 목록은 덮어쓰지 않는다)
  nonstop.py add    <세션> <제목>            작업을 뒤에 더한다
  nonstop.py set    <세션> <번호> <상태> <메모>  상태를 바꾸고 메모(PR 주소·질문·사유)를 남긴다. todo 로 되돌릴 때만 메모를 뺀다
  nonstop.py decide <세션> <번호> <내용>      권장안으로 정한 것을 적는다
  nonstop.py show   <세션>                   아침 보고를 출력한다
  nonstop.py hook                            hook 입력(JSON)을 stdin 으로 받는다
"""
import json
import os
import sys

STATES = ("todo", "done", "hold", "blocked")
ROOT = os.path.expanduser("~/.cache/fade-nonstop")
HOLD_HINT = (
    "지켜보는 사람이 없다. 묻지 않는다. "
    "`nonstop.py set <세션> <번호> hold \"질문 · 선택지 · 권장안\"` 으로 적고 다음 작업으로 간다."
)


def path(session):
    if not session or "$" in session or "/" in session:
        sys.exit("세션 ID 가 올바르지 않다: %r" % session)
    return os.path.join(ROOT, session, "tasks.json")


def load(session):
    try:
        with open(path(session), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save(session, tasks):
    p = path(session)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def remaining(tasks):
    return [t for t in tasks or [] if t["state"] == "todo"]


def report(tasks):
    titles = {"done": "끝난 것", "hold": "보류 (답이 필요한 것)", "blocked": "막힌 것", "todo": "남은 것"}
    count = lambda rows: len(list(rows))
    done = [t for t in tasks if t["state"] == "done"]
    prs = count(t for t in done if "/pull/" in t["note"])
    out = ["PR %d개 · 변경 없이 끝남 %d개 · 보류 %d개 · 막힘 %d개 · 남음 %d개" % (
        prs, len(done) - prs,
        count(t for t in tasks if t["state"] == "hold"),
        count(t for t in tasks if t["state"] == "blocked"),
        len(remaining(tasks))), ""]
    for state in ("done", "hold", "blocked", "todo"):
        rows = [t for t in tasks if t["state"] == state]
        if not rows:
            continue
        out.append("## " + titles[state])
        for t in rows:
            out.append("- %d. %s%s" % (t["id"], t["title"], " — " + t["note"] if t["note"] else ""))
        out.append("")
    decided = [(t, d) for t in tasks for d in t["decided"]]
    if decided:
        out.append("## 권장안으로 정한 것")
        out += ["- %d. %s — %s" % (t["id"], t["title"], d) for t, d in decided]
    return "\n".join(out).rstrip()


def task(tasks, number):
    for t in tasks:
        if str(t["id"]) == str(number):
            return t
    sys.exit("없는 작업 번호: %s" % number)


def hook():
    data = json.load(sys.stdin)
    left = remaining(load(data.get("session_id", "")))
    if not left:
        return
    event = data.get("hook_event_name")
    nxt = "%d. %s" % (left[0]["id"], left[0]["title"])
    if event == "Stop":
        out = {
            "decision": "block",
            "reason": "남은 작업 %d개. 턴을 끝내지 않는다. 다음 작업: %s. "
            "방금 작업을 끝냈거나 보류했다면 `nonstop.py set` 으로 상태부터 바꾼다. %s" % (len(left), nxt, HOLD_HINT),
        }
    elif event == "PreToolUse":
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": HOLD_HINT,
        }}
    elif event == "PermissionRequest":
        out = {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": "deny",
                "message": "지켜보는 사람이 없어 승인할 수 없다. 형태를 바꿔 다시 시도하지 않는다. "
                "이 일 없이 작업을 끝낼 수 없으면 `nonstop.py set <세션> <번호> blocked \"사유\"` 로 적고 다음 작업으로 간다.",
            },
        }}
    else:
        return
    print(json.dumps(out, ensure_ascii=False))


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd == "hook":
        return hook()
    if len(argv) < 3:
        sys.exit(__doc__)
    session = argv[2]
    args = argv[3:]
    need = {"add": 1, "set": 2, "decide": 2}
    if len(args) < need.get(cmd, 0):
        sys.exit(__doc__)
    if cmd == "init":
        left = remaining(load(session))
        if left:
            sys.exit("남은 작업 %d개가 있는 목록을 덮어쓰지 않는다. 작업을 더하려면 add 를 쓴다" % len(left))
        tasks = [{"id": i, "title": t, "state": "todo", "note": "", "decided": []} for i, t in enumerate(args, 1)]
        if not tasks:
            sys.exit("작업 제목이 하나도 없다")
        save(session, tasks)
    else:
        tasks = load(session)
        if tasks is None:
            sys.exit("작업 목록이 없다. init 부터 한다")
        if cmd == "add":
            tasks.append({"id": len(tasks) + 1, "title": args[0], "state": "todo", "note": "", "decided": []})
        elif cmd == "set":
            number, state, note = args[0], args[1], "".join(args[2:3])
            if state not in STATES:
                sys.exit("상태는 %s 중 하나다" % " ".join(STATES))
            if state != "todo" and not note:
                sys.exit("%s 에는 메모가 있어야 한다 (done: PR 주소나 근거, hold: 질문, blocked: 사유)" % state)
            t = task(tasks, number)
            t["state"] = state
            t["note"] = note
        elif cmd == "decide":
            task(tasks, args[0])["decided"].append(args[1])
        elif cmd != "show":
            sys.exit(__doc__)
        if cmd != "show":
            save(session, tasks)
    print(report(tasks))
    left = remaining(tasks)
    print("\n남은 작업 %d개%s" % (len(left), (" — 다음: %d. %s" % (left[0]["id"], left[0]["title"])) if left else ". 전부 정리됐다"))


if __name__ == "__main__":
    main(sys.argv)
