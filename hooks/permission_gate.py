#!/usr/bin/env python3
"""사람 없는 fade job 에서 승인 창이 뜨려 하면 기다리지 않고 거부한다.

`job.py start --unattended` 로 시작한 작업의 브랜치에서만 판정한다. 그 밖의 세션이나 이 훅이 오류로 죽은
경우에는 아무 판정도 내지 않고 평소처럼 승인 창이 뜬다. 막기만 하고 허용은 하지 않는다. 거부하면 실수 기록에 한 줄 남긴다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "job"))
import job  # noqa: E402


def main():
    data = json.load(sys.stdin)
    cwd = data.get("cwd") or os.getcwd()
    state = job.load(cwd)
    if state is None or not state.get("unattended") or state.get("branch") != job.branch(cwd):
        return
    what = data.get("tool_name", "")
    command = (data.get("tool_input") or {}).get("command")
    if command:
        what += " `" + command + "`"
    message = ("사람 없는 fade job 이라 승인을 기다리지 않고 거부했다: " + what + ". 형태를 바꿔 다시 시도하지 않는다. "
               "완료 기준을 채우는 데 꼭 필요한 일이면 `job.py stop \"<막힌 자리와 이유>\"` 로 남기고 사용자에게 보고한 뒤 끝낸다. "
               "필요하지 않은 곁가지(정리, 미리 보기)면 그 일을 빼고 진행하고 보고에 적는다.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest",
                                             "decision": {"behavior": "deny", "message": message, "interrupt": False}}},
                     ensure_ascii=False), flush=True)
    job.add_mistake(cwd, state, "permission", "승인이 필요한 일을 하려 했다: " + what)  # 판정을 먼저 내보내 기록이 실패해도 거부한다


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 훅이 죽으면 판정하지 않고 평소 승인 창으로 넘긴다
        print("fade permission_gate: %s" % e, file=sys.stderr)
