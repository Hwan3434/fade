#!/usr/bin/env python3
"""job 의 단계 기록. 병합 직전에 fade 훅(hooks/merge_gate.py)이 이 기록을 본다.

기록은 작업 중인 워크트리의 git 폴더 안 fade-job.json 한 파일이다. 커밋되지 않고 워크트리와 함께 사라진다.
병합 조건의 green, 증거, 써 보기, 리뷰는 지금 커밋에서 찍힌 것만 친다. 고친 커밋이 생기면 다시 한다.
실수 기록은 작업과 레포를 넘어 모이는 한 파일(~/.claude/fade/mistakes.jsonl, 환경 변수 FADE_MISTAKES 로 바꾼다)이다.
stop 과 slip, 그리고 병합 훅과 승인 창 훅이 막을 때 한 줄씩 붙는다.

  job.py start   <제목> [--pr-only] [--unattended]
                                         작업을 시작한다. PR 까지만이면 --pr-only, 계획서가 「사용자: 없음」이면 --unattended
  job.py scope   merge|pr                범위를 바꾼다 (사용자가 범위를 바꿨을 때)
  job.py red     <테스트 명령>           명령을 돌려 실패할 때만 기록한다 (구현 전)
  job.py green                           red 의 명령을 다시 돌려 통과할 때만 기록한다 (구현 후)
  job.py no-test <이유>                  레포에 테스트 실행 장치가 없을 때 red·green 대신 이유를 적는다
  job.py evidence <완료 기준> <파일>...   스크린샷, 로그 같은 증거 파일을 기준에 붙인다
  job.py log     <완료 기준> <명령>       명령을 돌려 출력 전체를 파일로 남기고 증거로 붙인다
  job.py drop    <완료 기준>             그 기준에 붙인 증거를 모두 지운다 (다시 붙이기 전에)
  job.py tried   <무엇을 어떻게> <파일>...  직접 써 본 기록과 그 화면·출력 파일
  job.py try-na  <이유>                  써 볼 화면도 명령도 없는 작업일 때
  job.py human   <사람이 볼 것>           사람만 판정할 수 있는 것이 남았을 때. 직접 써 보기를 대신하고, 병합을 막는다
  job.py review-files <base>             명세 축 리뷰어에게 줄 show 출력과 base 와의 diff 를 워크트리 안
                                         .fade-review/ (git 이 무시하는 폴더)에 쓴다. 계획서 원문은 부르는 쪽이 plan.md 로 쓴다
  job.py review  <남은 막는 지적 수> [<요약>]
                                         코드 리뷰 결과. 지금 커밋에서 남은 막는 지적이 0 이어야 병합한다
  job.py door    one-way|two-way <이유와 영향 범위>
                                         되돌릴 수 있는가. 기록이 없거나 one-way(한쪽 문)면 병합을 막는다
  job.py stop    <이유>                  해결하지 못했거나 사용자 결정이 필요해 멈춘다. 병합을 막고 실수 기록에 남긴다
  job.py slip    review|ci|user <무엇을 잘못했나>
                                         리뷰에서 고친 막는 지적, CI 실패, 사용자 지적을 실수 기록에 남긴다
  job.py mark    <줄 번호> key|handled <값>
                                         실수 기록 한 줄의 key(같은 실수끼리 묶는 이름)나 처리를 적는다. git 레포 밖에서도 돈다
  job.py pr      <PR 주소>
  job.py check                           병합 조건을 본다. 빠진 것이 있으면 종료 코드 1
  job.py merged  <병합 커밋> [<base CI 결과>]
  job.py show [--full]                   PR 본문과 보고에 붙일 기록. 첫 줄은 상태다. --full 이면 로그 파일 내용도 붙인다
"""
import json
import os
import subprocess
import sys
import time

TAIL = 40


def git_dir(cwd):
    r = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def state_path(cwd):
    d = git_dir(cwd)
    return os.path.join(d, "fade-job.json") if d else None


def load(cwd):
    p = state_path(cwd)
    if not p or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(cwd, state):
    # 데스크톱 앱이 만든 워크트리에서 시작한 뒤 레포 규칙대로 브랜치를 새로 따는 일이 있어, 기록할 때마다 지금 브랜치로 맞춘다
    state["branch"] = branch(cwd)
    p = state_path(cwd)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def branch(cwd):
    r = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def head(cwd):
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "(커밋 없음)"


def short(sha):
    return sha[:7] if sha != "(커밋 없음)" else sha


def dirty(cwd):
    # 스크린샷 같은 추적하지 않는 파일은 빼고, 커밋하지 않은 코드 변경만 본다
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd, capture_output=True, text=True)
    return bool(r.stdout.strip())


def run(cwd, command):
    r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def tail_of(text):
    return "\n".join(text.splitlines()[-TAIL:])


def at(record):
    return short(record["head"]) + (", 커밋 전 변경 있음" if record.get("dirty") else "")


def where(cwd):
    return {"head": head(cwd), "dirty": dirty(cwd)}


def mistakes_path():
    return os.environ.get("FADE_MISTAKES") or os.path.expanduser("~/.claude/fade/mistakes.jsonl")


def main_checkout(cwd):
    """워크트리는 작업이 끝나면 사라지니, 실수 기록에는 메인 체크아웃 경로를 레포로 남긴다."""
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                       capture_output=True, text=True)
    common = r.stdout.strip()
    return os.path.dirname(common) if r.returncode == 0 and os.path.basename(common) == ".git" else common


def add_mistake(cwd, state, source, what):
    """실수 기록에 한 줄을 붙인다. 파일과 폴더가 없으면 만든다."""
    row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo": main_checkout(cwd), "branch": branch(cwd),
           "pr": state.get("pr") or "", "source": source, "what": what, "key": "", "handled": ""}
    path = mistakes_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def mark(args):
    if len(args) < 3 or args[1] not in ("key", "handled"):
        sys.exit("job.py mark <줄 번호> key|handled <값>")
    path = mistakes_path()
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    if not args[0].isdigit() or not 1 <= int(args[0]) <= len(lines):
        sys.exit("실수 기록에 없는 줄이다: %s (%d줄)" % (args[0], len(lines)))
    n = int(args[0]) - 1
    row = json.loads(lines[n])
    row[args[1]] = args[2]
    lines[n] = json.dumps(row, ensure_ascii=False)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    print("%d: %s" % (n + 1, lines[n]))


def status(state):
    if state["merged"]:
        return "병합됨"
    if state.get("stopped"):
        return "멈춤(%s)" % state["stopped"]
    if state["scope"] == "pr" and state["pr"]:
        return "PR 까지"
    return "진행 중"


def missing(state, cwd):
    """병합을 막는 빠진 것들. 비어 있으면 병합해도 된다. green, 증거, 써 보기, 리뷰는 지금 커밋 것만 친다."""
    now = head(cwd)
    s = short(now)
    out = []
    if state.get("stopped"):
        out.append("멈춤: " + state["stopped"])
    if state["scope"] == "pr":
        out.append("이번 작업은 PR 까지만이다. 병합하지 않는다")
    if not state["no_test"]:
        if not (state["red"] and state["green"]):
            out.append("테스트: 구현 전 실패(red)와 구현 후 통과(green)가 없다. 장치가 없으면 no-test 로 이유를 적는다")
        elif state["green"]["head"] != now or state["green"].get("dirty"):
            out.append("테스트: green 을 마지막 커밋(%s)에서 커밋 전 변경 없이 다시 돌리지 않았다" % s)
    criteria = list(dict.fromkeys(e["criterion"] for e in state["evidence"]))
    if not criteria:
        out.append("증거: 완료 기준에 붙인 로그나 스크린샷이 없다")
    for c in criteria:
        if not any(e["criterion"] == c and e.get("head") == now for e in state["evidence"]):
            out.append("증거: 「%s」를 마지막 커밋(%s)에서 다시 남기지 않았다" % (c, s))
    if not state["try_na"] and not state["human"]:
        if not state["tried"]:
            out.append("직접 써 보기: 기록이 없다. 써 볼 것이 없는 작업이면 try-na, 지금 못 하면 human 으로 남긴다")
        elif not any(t.get("head") == now for t in state["tried"]):
            out.append("직접 써 보기: 마지막 커밋(%s)에서 다시 써 보지 않았다" % s)
    door = state.get("door")
    if not door:
        out.append("되돌릴 수 있는가: 기록이 없다. job.py door one-way|two-way \"<이유와 영향 범위>\" 로 남긴다")
    elif door["kind"] == "one-way":
        out.append("한쪽 문(되돌릴 수 없음): %s. 병합은 사용자가 정한다" % door["why"])
    review = state.get("review")
    if not review:
        out.append("리뷰: 기록이 없다. 코드 리뷰를 돌리고 job.py review <남은 막는 지적 수> 로 남긴다")
    elif review["head"] != now or review.get("dirty"):
        out.append("리뷰: 마지막 커밋(%s)에서 커밋 전 변경 없이 다시 하지 않았다" % s)
    elif review["left"]:
        out.append("리뷰: 남은 막는 지적 %d개" % review["left"])
    for h in state["human"]:
        out.append("사람이 볼 것: " + h)
    return out


def file_lines(files, full):
    out = []
    for f in files:
        out.append("    - " + f)
        if full and f.endswith(".log") and os.path.isfile(f):
            with open(f, encoding="utf-8", errors="replace") as fh:
                out += ["", "      ```text"] + ["      " + line for line in fh.read().splitlines()] + ["      ```", ""]
    return out


def show(state, cwd, full=False):
    lines = ["상태: " + status(state), "", "## 작업 기록 (fade job)", "", "- 작업: " + state["title"],
             "- 범위: " + ("PR 까지" if state["scope"] == "pr" else "병합까지")]
    if state.get("unattended"):
        lines.append("- 사람 없음: 승인 창이 뜨면 기다리지 않고 거부되어 멈춘다")
    if state.get("stopped"):
        lines.append("- 멈춤: " + state["stopped"])
    if state["no_test"]:
        lines.append("- 테스트: 없음 — " + state["no_test"])
    for old in state.get("red_history", []):
        lines.append("- 앞서 기록한 실패(red, %s): `%s` → 종료 코드 %d" % (at(old), old["cmd"], old["code"]))
    if state["red"]:
        lines.append("- 구현 전 실패(red, %s): `%s` → 종료 코드 %d" % (at(state["red"]), state["red"]["cmd"], state["red"]["code"]))
    if state["green"]:
        lines.append("- 구현 후 통과(green, %s): `%s`" % (at(state["green"]), state["red"]["cmd"]))
    if state["evidence"]:
        lines.append("- 증거:")
        for e in state["evidence"]:
            lines.append("  - " + e["criterion"] + (" (명령 `%s`, 종료 코드 %d)" % (e["cmd"], e["code"]) if e.get("cmd") else "")
                         + (" (커밋 %s)" % at(e) if e.get("head") else ""))
            lines += file_lines(e["files"], full)
    if state["tried"]:
        lines.append("- 직접 써 보기:")
        for t in state["tried"]:
            lines.append("  - " + t["what"] + (" (커밋 %s)" % at(t) if t.get("head") else ""))
            lines += file_lines(t["files"], full)
    if state["try_na"]:
        lines.append("- 직접 써 보기: 해당 없음 — " + state["try_na"])
    for h in state["human"]:
        lines.append("- 사람이 볼 것: " + h)
    door = state.get("door")
    if door:
        lines.append("- 되돌릴 수 있는가: %s — %s" % ("한쪽 문" if door["kind"] == "one-way" else "양쪽 문", door["why"]))
    review = state.get("review")
    if review:
        lines.append("- 리뷰(%s): 남은 막는 지적 %d개%s" % (at(review), review["left"], " — " + review["note"] if review["note"] else ""))
    if state["pr"]:
        lines.append("- PR: " + state["pr"])
    if state["merged"]:
        lines.append("- 병합: " + state["merged"]["commit"] + (" · " + state["merged"]["ci"] if state["merged"]["ci"] else ""))
    left = missing(state, cwd)
    if left and not state["merged"]:
        lines += ["", "병합 전에 빠진 것:"] + ["- " + m for m in left]
    # 이 출력은 공개 PR 에도 붙으니 사용자 이름이 든 홈 경로를 줄인다
    return "\n".join(lines).replace(os.path.expanduser("~"), "~")


def review_files(cwd, state, base):
    """리뷰어는 읽기 도구만 있어 작업 폴더 밖을 읽으려면 승인이 필요하고, 데스크톱 앱은 파일 도구로 git 폴더에
    쓰는 것을 막는다. 그래서 워크트리 안에 두되, 안의 .gitignore 가 폴더째 git 에서 빼게 한다."""
    r = subprocess.run(["git", "diff", base + "...HEAD"], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("base 와의 diff 를 만들지 못했다: " + r.stderr.strip())
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True).stdout.strip()
    folder = os.path.join(top, ".fade-review")
    os.makedirs(folder, exist_ok=True)
    for name, text in ((".gitignore", "*\n"), ("show.txt", show(state, cwd) + "\n"), ("diff.patch", r.stdout)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    return folder


def need_files(paths):
    if not paths:
        sys.exit("파일이 하나도 없다. 화면이면 스크린샷, 명령이면 출력 파일의 경로를 준다")
    for p in paths:
        if not os.path.isfile(p):
            sys.exit("없는 파일: " + p)
    return [os.path.abspath(p) for p in paths]


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd, args, cwd = argv[1], argv[2:], os.getcwd()
    if cmd == "mark":
        mark(args)
        return
    if not git_dir(cwd):
        sys.exit("git 레포 안에서 돌린다")
    state = load(cwd)
    if cmd == "start":
        if state and not state["merged"] and state.get("branch") == branch(cwd):
            sys.exit("이 브랜치에는 이미 시작한 작업이 있다: " + state["title"])
        if not args:
            sys.exit("작업 제목이 없다")
        state = {"title": args[0], "scope": "pr" if "--pr-only" in args else "merge", "started": time.time(),
                 "branch": branch(cwd), "unattended": "--unattended" in args,
                 "red": None, "green": None, "no_test": None, "evidence": [], "tried": [], "try_na": None,
                 "human": [], "review": None, "door": None, "stopped": None, "pr": None, "merged": None}
        save(cwd, state)
        print(show(state, cwd))
        return
    if state is None:
        sys.exit("작업 기록이 없다. job.py start 부터 한다")
    need = {"scope": 1, "red": 1, "no-test": 1, "evidence": 2, "log": 2, "drop": 1, "tried": 1, "try-na": 1, "human": 1,
            "review": 1, "review-files": 1, "door": 2, "stop": 1, "slip": 2, "pr": 1, "merged": 1}
    if len(args) < need.get(cmd, 0):
        sys.exit(__doc__)
    if cmd == "scope":
        if args[0] not in ("merge", "pr"):
            sys.exit("범위는 merge 나 pr 이다")
        state["scope"] = args[0]
    elif cmd == "red":
        code, out = run(cwd, args[0])
        if code == 0:
            sys.exit("테스트가 실패하지 않는다. 이번 변경을 판정하지 못하는 테스트다. 테스트를 고친다\n" + tail_of(out))
        if state["red"]:
            state.setdefault("red_history", []).append(state["red"])
        state["red"] = {"cmd": args[0], "code": code, "head": head(cwd), "dirty": dirty(cwd), "tail": tail_of(out)}
        state["green"] = None
    elif cmd == "green":
        if not state["red"]:
            sys.exit("red 가 없다. 구현 전에 실패하는 테스트부터 기록한다")
        code, out = run(cwd, state["red"]["cmd"])
        if code != 0:
            sys.exit("테스트가 아직 통과하지 않는다 (종료 코드 %d)\n%s" % (code, tail_of(out)))
        state["green"] = {"head": head(cwd), "dirty": dirty(cwd), "tail": tail_of(out)}
    elif cmd == "no-test":
        state["no_test"] = args[0]
    elif cmd == "evidence":
        state["evidence"].append({"criterion": args[0], "files": need_files(args[1:]), **where(cwd)})
    elif cmd == "drop":
        kept = [e for e in state["evidence"] if e["criterion"] != args[0]]
        if len(kept) == len(state["evidence"]):
            sys.exit("그 기준에 붙인 증거가 없다: " + args[0])
        state["evidence"] = kept
    elif cmd == "log":
        code, out = run(cwd, args[1])
        logs = os.path.join(git_dir(cwd), "fade-job-logs")
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, "%02d.log" % (len([f for f in os.listdir(logs) if f.endswith(".log")]) + 1))
        with open(path, "w", encoding="utf-8") as f:
            f.write("$ %s\n%s\n(종료 코드 %d)\n" % (args[1], out.rstrip("\n"), code))
        state["evidence"].append({"criterion": args[0], "files": [path], "cmd": args[1], "code": code, **where(cwd)})
        print(tail_of(out))
    elif cmd == "tried":
        state["tried"].append({"what": args[0], "files": need_files(args[1:]), **where(cwd)})
    elif cmd == "try-na":
        state["try_na"] = args[0]
    elif cmd == "human":
        state["human"].append(args[0])
    elif cmd == "review":
        if not args[0].isdigit():
            sys.exit("남은 막는 지적 수는 0 이상의 정수다")
        state["review"] = {"left": int(args[0]), "note": " ".join(args[1:2]), **where(cwd)}
    elif cmd == "door":
        if args[0] not in ("one-way", "two-way") or not args[1].strip():
            sys.exit("job.py door one-way|two-way \"<이유와 영향 범위>\"")
        state["door"] = {"kind": args[0], "why": args[1]}
    elif cmd == "stop":
        state["stopped"] = args[0]
        save(cwd, state)
        add_mistake(cwd, state, "stop", args[0])
    elif cmd == "slip":
        if args[0] not in ("review", "ci", "user") or not args[1].strip():
            sys.exit("job.py slip review|ci|user \"<무엇을 잘못했나>\". 병합 훅·승인 창 훅·stop 은 스스로 남긴다")
        add_mistake(cwd, state, args[0], args[1])
    elif cmd == "pr":
        state["pr"] = args[0]
    elif cmd == "merged":
        state["merged"] = {"commit": args[0], "ci": args[1] if len(args) > 1 else ""}
    elif cmd == "review-files":
        folder = review_files(cwd, state, args[0])
        print("%s 에 show.txt, diff.patch 를 썼다. 계획서 원문을 %s 로 쓰고 세 경로를 리뷰어에게 준다"
              % (folder, os.path.join(folder, "plan.md")))
        return
    elif cmd == "check":
        left = missing(state, cwd)
        print("\n".join("- " + m for m in left) if left else "병합 조건을 모두 채웠다")
        sys.exit(1 if left else 0)
    elif cmd != "show":
        sys.exit(__doc__)
    if cmd != "show":
        save(cwd, state)
    print(show(state, cwd, full="--full" in args))


if __name__ == "__main__":
    main(sys.argv)
