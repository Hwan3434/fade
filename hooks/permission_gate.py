#!/usr/bin/env python3
"""사람 없는 fade job 에서 승인 창이 뜨려 하면 기다리지 않고 거부한다.

`job.py start --unattended` 로 시작한 작업의 브랜치에서만 판정한다. 기록은 세션의 현재 폴더만이 아니라
명령이 가리키는 폴더(같은 명령 줄의 cd, git -C)와 파일 도구가 고치는 파일의 폴더에서도 찾는다.
그 밖의 세션이나 이 훅이 오류로 죽은 경우에는 아무 판정도 내지 않고 평소처럼 승인 창이 뜬다. 막기만 하고 허용은 하지 않는다. 거부하면 실수 기록에 한 줄 남긴다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "job"))
import job  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_gate  # noqa: E402


def unattended_job(data):
    """승인 창을 띄우려는 일이 닿는 사람 없는 job 의 (기록, 워크트리). 없으면 None."""
    cwd = data.get("cwd") or os.getcwd()
    tool_input = data.get("tool_input") or {}
    try:
        places = [here for here, _ in merge_gate.located(tool_input.get("command") or "", cwd)]
    except ValueError:  # 셸은 받지만 shlex 가 못 읽는 명령($'...' 등)은 세션 폴더로만 판정한다
        places = []
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(tool_input.get(key), str):
            path = os.path.join(cwd, tool_input[key])
            while path and not os.path.isdir(path) and os.path.dirname(path) != path:
                path = os.path.dirname(path)  # 아직 없는 폴더에 쓰는 Write 는 있는 가장 가까운 위 폴더로 찾는다
            places.append(path)
    for place in [p for p in places if p] + [cwd]:
        found = merge_gate.job_at(place, merged_too=True)
        if found and found[0].get("unattended"):
            return found
    return None


def main():
    data = json.load(sys.stdin)
    found = unattended_job(data)
    if not found:
        return
    state, cwd = found
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
