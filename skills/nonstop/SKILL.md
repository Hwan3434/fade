---
name: nonstop
description: 지켜보는 사람 없이 받은 작업 목록을 끝까지 돈다. 작업마다 PR 까지 올리고, 물어야 할 것은 보류로 적어 두고 다음 작업으로 간다. 남은 작업이 있는 동안 턴 종료·질문·권한 창을 hook 이 막는다. 사용자가 「/fade:nonstop」으로 직접 부를 때만 쓴다.
disable-model-invocation: true
model: opus
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/nonstop.py *)
hooks:
  Stop:
    - hooks:
        - type: command
          command: '"${CLAUDE_PLUGIN_ROOT}"/skills/nonstop/nonstop.py hook'
  PreToolUse:
    - matcher: "AskUserQuestion"
      hooks:
        - type: command
          command: '"${CLAUDE_PLUGIN_ROOT}"/skills/nonstop/nonstop.py hook'
  PermissionRequest:
    - hooks:
        - type: command
          command: '"${CLAUDE_PLUGIN_ROOT}"/skills/nonstop/nonstop.py hook'
---

# nonstop

지켜보는 사람이 없다. 받은 작업을 할 수 있는 데까지 끝내 놓는 것이 목적이다. 한 작업이 막혀도 나머지는 계속한다.

작업 목록은 `${CLAUDE_SKILL_DIR}/nonstop.py` 로만 다룬다. 이 세션의 ID 는 `${CLAUDE_SESSION_ID}` 다. 아래 명령의 `<세션>` 자리에 넣는다.

## 순서

1. 받은 요청을 작업 단위로 나눠 목록을 만든다. 서로 기대는 일은 한 작업으로 묶는다.
   `nonstop.py init <세션> "작업 제목" "작업 제목" ...`
2. 목록 순서대로 한다. 워크트리 준비나 검사처럼 오래 걸리는 것을 기다리는 동안에는 다음 작업을 먼저 한다. 작업 하나가 정리될 때마다 상태를 바꾼다.
   - 끝났다: `nonstop.py set <세션> <번호> done "PR 주소"`. 고칠 것이 없어 PR 없이 끝났으면 주소 대신 근거를 적는다.
   - 사용자만 답할 수 있는 것이 있어 더 못 간다: `nonstop.py set <세션> <번호> hold "질문 · 선택지 · 권장안 · 답이 오면 이어서 할 일"`
   - 권한이나 환경에 막혔다: `nonstop.py set <세션> <번호> blocked "막힌 자리와 사유"`
3. 남은 작업이 없으면 `nonstop.py show <세션>` 의 출력을 그대로 마지막 답으로 낸다.

## 작업 하나를 하는 방법

작업 하나하나를 `fade:job` 스킬로 수행한다(사용자: 없음). 이 스킬은 그 위에 아래만 더한다.

- 작업마다 자기 브랜치와 PR 을 갖는다. 앞 작업의 브랜치 위에 쌓지 않는다. 앞 작업이 보류되거나 막혀도 이 작업은 혼자 선다.
- 작업의 끝은 PR 을 올린 것이다. CI 를 기다리지 않고 `done` 으로 적은 뒤 다음 작업으로 간다.
- 원인을 찾지 못했으면 고치지 않는다. `hold` 에 찾은 데까지 적는다.
- `job` 이 멈춰서 물으라는 때는 묻지 않고 `hold` 로 적는다. `job` 이 스스로 고른 것은 `nonstop.py decide <세션> <번호> "무엇을 왜 골랐는지"` 로도 남긴다.

## 레포가 확인을 요구하는 일

레포가 확인을 요구하는 일은 이 스킬이 거부한다. 거부되면 `blocked` 로 적고 다음 작업으로 간다.

## 묻는 대신 하는 것

- 사용자가 눈으로 봐야 하거나 되돌릴 수 없는 결정은 정하지 않는다. 그 작업에서 그 결정 없이 할 수 있는 데까지 하고 `hold` 로 적는다.
- 권한이 거부되면 형태를 바꿔 다시 시도하지 않는다. `blocked` 로 적고 다음 작업으로 간다.
- 질문으로 턴을 끝내지 않는다. 남은 작업이 있으면 턴 종료와 질문 도구, 권한 창이 hook 에 막힌다.

남은 작업이 0 이 되면 hook 은 아무것도 막지 않는다. 그 뒤에는 평소처럼 사용자와 대화한다.
