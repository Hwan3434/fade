#!/usr/bin/env python3
"""nonstop 의 작업 목록.

작업 목록은 ~/.cache/fade-nonstop/<세션 ID>/tasks.json 한 파일이다.
상태: todo(남음) done(끝남) hold(사용자 답이 필요해 보류) blocked(권한·환경에 막힘)

  nonstop.py init   <세션> <제목>...         작업 목록을 새로 만든다 (남은 작업이 있는 목록은 덮어쓰지 않는다)
  nonstop.py add    <세션> <제목>            작업을 뒤에 더한다
  nonstop.py set    <세션> <번호> <상태> <메모>  상태를 바꾸고 메모(PR 주소·질문·사유)를 남긴다. todo 로 되돌릴 때만 메모를 뺀다
  nonstop.py decide <세션> <번호> <내용>      권장안으로 정한 것을 적는다
  nonstop.py show   <세션>                   아침 보고를 출력한다

플러그인의 bin/nonstop.py 가 이 파일을 부르고, Claude Code 가 bin/ 을 Bash 도구의 PATH 에 두니 경로 없이 부른다.
init, add, set, decide 는 무엇을 했는지와 남은 작업 한 줄만 찍는다. 보고 전체는 show 에서만 나온다.
"""
import json
import os
import sys

STATES = ("todo", "done", "hold", "blocked")
ROOT = os.path.expanduser("~/.cache/fade-nonstop")


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
    out = ["PR %d개 · PR 없이 끝남 %d개 · 보류 %d개 · 막힘 %d개 · 남음 %d개" % (
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


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd = argv[1]
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
        said = "작업 %d개로 목록을 만들었다" % len(tasks)
    else:
        tasks = load(session)
        if tasks is None:
            sys.exit("작업 목록이 없다. init 부터 한다")
        if cmd == "add":
            tasks.append({"id": len(tasks) + 1, "title": args[0], "state": "todo", "note": "", "decided": []})
            said = "더했다: %d. %s" % (len(tasks), args[0])
        elif cmd == "set":
            number, state, note = args[0], args[1], "".join(args[2:3])
            if state not in STATES:
                sys.exit("상태는 %s 중 하나다" % " ".join(STATES))
            if state != "todo" and not note:
                sys.exit("%s 에는 메모가 있어야 한다 (done: PR 주소나 근거, hold: 질문, blocked: 사유)" % state)
            t = task(tasks, number)
            t["state"] = state
            t["note"] = note
            said = "%d. %s → %s" % (t["id"], t["title"], state)
        elif cmd == "decide":
            t = task(tasks, args[0])
            t["decided"].append(args[1])
            said = "%d. %s 에 권장안으로 정한 것을 적었다" % (t["id"], t["title"])
        elif cmd != "show":
            sys.exit(__doc__)
        if cmd != "show":
            save(session, tasks)
    # 보고 전체는 show 에서만 낸다. 기록 명령마다 전체를 찍으면 같은 글이 맥락에 쌓인다
    print(report(tasks) + "\n" if cmd == "show" else said)
    left = remaining(tasks)
    print("남은 작업 %d개%s" % (len(left), (" — 다음: %d. %s" % (left[0]["id"], left[0]["title"])) if left else ". 전부 정리됐다"))


if __name__ == "__main__":
    main(sys.argv)
