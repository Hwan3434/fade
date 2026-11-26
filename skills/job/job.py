#!/usr/bin/env python3
"""job 의 단계 기록. 병합 직전에 fade 훅(hooks/merge_gate.py)이 이 기록을 본다.

기록은 작업 중인 워크트리의 git 폴더 안 fade-job.json 한 파일이다. 커밋되지 않고 워크트리와 함께 사라진다.

  job.py start   <제목> [--pr-only]      작업을 시작한다. 사용자가 PR 까지만 하라고 했으면 --pr-only
  job.py red     <테스트 명령>           명령을 돌려 실패할 때만 기록한다 (구현 전)
  job.py green                           red 의 명령을 다시 돌려 통과할 때만 기록한다 (구현 후)
  job.py no-test <이유>                  레포에 테스트 실행 장치가 없을 때 red·green 대신 이유를 적는다
  job.py evidence <완료 기준> <파일>...   스크린샷, 로그 같은 증거 파일을 기준에 붙인다
  job.py log     <완료 기준> <명령>       명령을 돌려 출력을 파일로 남기고 증거로 붙인다
  job.py tried   <무엇을 어떻게> <파일>...  직접 써 본 기록과 그 화면·출력 파일
  job.py try-na  <이유>                  써 볼 화면도 명령도 없는 작업일 때
  job.py human   <사람이 볼 것>           사람만 판정할 수 있는 것이 남았을 때. 병합을 막는다
  job.py pr      <PR 주소>
  job.py check                           병합 조건을 본다. 빠진 것이 있으면 종료 코드 1
  job.py merged  <병합 커밋> [<base CI 결과>]
  job.py show                            PR 본문과 보고에 붙일 기록
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
    p = state_path(cwd)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def branch(cwd):
    r = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def head(cwd):
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() or "(커밋 없음)"


def run(cwd, command):
    r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).splitlines()
    return r.returncode, "\n".join(out[-TAIL:])


def missing(state):
    """병합을 막는 빠진 것들. 비어 있으면 병합해도 된다."""
    out = []
    if state["scope"] == "pr":
        out.append("이번 작업은 PR 까지만이다. 병합하지 않는다")
    if not state["no_test"] and not (state["red"] and state["green"]):
        out.append("테스트: 구현 전 실패(red)와 구현 후 통과(green)가 없다. 장치가 없으면 no-test 로 이유를 적는다")
    if not state["evidence"]:
        out.append("증거: 완료 기준에 붙인 로그나 스크린샷이 없다")
    if not state["tried"] and not state["try_na"]:
        out.append("직접 써 보기: 기록이 없다. 써 볼 것이 없는 작업이면 try-na 로 이유를 적는다")
    for h in state["human"]:
        out.append("사람이 볼 것: " + h)
    return out


def show(state):
    lines = ["## 작업 기록 (fade job)", "", "- 작업: " + state["title"],
             "- 범위: " + ("PR 까지" if state["scope"] == "pr" else "병합까지")]
    if state["no_test"]:
        lines.append("- 테스트: 없음 — " + state["no_test"])
    if state["red"]:
        lines.append("- 구현 전 실패(red, %s): `%s` → 종료 코드 %d" % (state["red"]["head"], state["red"]["cmd"], state["red"]["code"]))
    if state["green"]:
        lines.append("- 구현 후 통과(green, %s): `%s`" % (state["green"]["head"], state["red"]["cmd"]))
    if state["evidence"]:
        lines.append("- 증거:")
        for e in state["evidence"]:
            lines.append("  - " + e["criterion"] + (" (명령 `%s`, 종료 코드 %d)" % (e["cmd"], e["code"]) if e.get("cmd") else ""))
            lines += ["    - " + f for f in e["files"]]
    if state["tried"]:
        lines.append("- 직접 써 보기:")
        for t in state["tried"]:
            lines.append("  - " + t["what"])
            lines += ["    - " + f for f in t["files"]]
    if state["try_na"]:
        lines.append("- 직접 써 보기: 해당 없음 — " + state["try_na"])
    for h in state["human"]:
        lines.append("- 사람이 볼 것: " + h)
    if state["pr"]:
        lines.append("- PR: " + state["pr"])
    if state["merged"]:
        lines.append("- 병합: " + state["merged"]["commit"] + (" · " + state["merged"]["ci"] if state["merged"]["ci"] else ""))
    left = missing(state)
    if left and not state["merged"]:
        lines += ["", "병합 전에 빠진 것:"] + ["- " + m for m in left]
    return "\n".join(lines)


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
    if not git_dir(cwd):
        sys.exit("git 레포 안에서 돌린다")
    state = load(cwd)
    if cmd == "start":
        if state and not state["merged"] and state.get("branch") == branch(cwd):
            sys.exit("이 브랜치에는 이미 시작한 작업이 있다: " + state["title"])
        if not args:
            sys.exit("작업 제목이 없다")
        state = {"title": args[0], "scope": "pr" if "--pr-only" in args else "merge", "started": time.time(),
                 "branch": branch(cwd),
                 "red": None, "green": None, "no_test": None, "evidence": [], "tried": [], "try_na": None,
                 "human": [], "pr": None, "merged": None}
        save(cwd, state)
        print(show(state))
        return
    if state is None:
        sys.exit("작업 기록이 없다. job.py start 부터 한다")
    need = {"red": 1, "no-test": 1, "evidence": 2, "log": 2, "tried": 1, "try-na": 1, "human": 1, "pr": 1, "merged": 1}
    if len(args) < need.get(cmd, 0):
        sys.exit(__doc__)
    if cmd == "red":
        code, tail = run(cwd, args[0])
        if code == 0:
            sys.exit("테스트가 실패하지 않는다. 이번 변경을 판정하지 못하는 테스트다. 테스트를 고친다\n" + tail)
        state["red"] = {"cmd": args[0], "code": code, "head": head(cwd), "tail": tail}
        state["green"] = None
    elif cmd == "green":
        if not state["red"]:
            sys.exit("red 가 없다. 구현 전에 실패하는 테스트부터 기록한다")
        code, tail = run(cwd, state["red"]["cmd"])
        if code != 0:
            sys.exit("테스트가 아직 통과하지 않는다 (종료 코드 %d)\n%s" % (code, tail))
        state["green"] = {"head": head(cwd), "tail": tail}
    elif cmd == "no-test":
        state["no_test"] = args[0]
    elif cmd == "evidence":
        state["evidence"].append({"criterion": args[0], "files": need_files(args[1:])})
    elif cmd == "log":
        code, tail = run(cwd, args[1])
        logs = os.path.join(git_dir(cwd), "fade-job-logs")
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, "%02d.log" % (len(state["evidence"]) + 1))
        with open(path, "w", encoding="utf-8") as f:
            f.write("$ %s\n%s\n(종료 코드 %d)\n" % (args[1], tail, code))
        state["evidence"].append({"criterion": args[0], "files": [path], "cmd": args[1], "code": code})
        print(tail)
    elif cmd == "tried":
        state["tried"].append({"what": args[0], "files": need_files(args[1:])})
    elif cmd == "try-na":
        state["try_na"] = args[0]
    elif cmd == "human":
        state["human"].append(args[0])
    elif cmd == "pr":
        state["pr"] = args[0]
    elif cmd == "merged":
        state["merged"] = {"commit": args[0], "ci": args[1] if len(args) > 1 else ""}
    elif cmd == "check":
        left = missing(state)
        print("\n".join("- " + m for m in left) if left else "병합 조건을 모두 채웠다")
        sys.exit(1 if left else 0)
    elif cmd != "show":
        sys.exit(__doc__)
    if cmd != "show":
        save(cwd, state)
    print(show(state))


if __name__ == "__main__":
    main(sys.argv)
