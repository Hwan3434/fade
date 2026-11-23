---
name: dispatch
description: "코드 변경 작업을 워커(목표가 걸린 레포의 전용 워크트리에서 도는 Claude Desktop 세션, 터미널에서는 `claude -p` 세션)에 맡긴다. 리드가 목적과 사용자가 준 정보로 `job` 계획서를 써서 워커를 띄우고, 워커의 보고를 사용자에게 옮기고, 워커가 붙인 증거를 완료 기준과 대조한다. 요청이 여러 레포에 걸치면 레포마다 워커를 따로 띄운다. 답만 필요한 조사는 대상이 아니다. Claude Desktop 과 터미널(CLI)에서 동작한다. 트리거: \"/fade:dispatch\", \"하위 세션으로 맡겨\", \"워커 띄워줘\", \"워크트리에서 작업시켜\"."
allowed-tools: Bash, Read, Grep, Glob, Skill, ToolSearch, mcp__ccd_session__start_session, mcp__ccd_session_mgmt__list_sessions, mcp__ccd_session_mgmt__list_events, mcp__ccd_session_mgmt__archive_session, mcp__ccd_pr__get_status, SendMessage, ListAgents
---

# dispatch — 워커에 작업 맡기기

| 용어 | 뜻 |
|---|---|
| 세션 | Claude 와의 대화 하나. 자기 폴더·기록·권한 설정을 가진다 |
| 리드 | 이 스킬을 부른 세션. 어느 레포에서 열었든, 여러 레포를 모아 둔 상위 폴더에서 열었든 같다. 워커를 띄우고, 보고를 옮기고, 증거를 완료 기준과 대조한다 |
| 워커 | 리드가 이 스킬로 띄운 세션. 목표가 걸린 레포의 자기 워크트리에서 작업 하나를 하고 PR 로 끝낸다. GitHub 원격이 없는 폴더면 그 폴더에서 하고 PR 없이 끝낸다. 사용자가 열어 말을 걸 수 있다 |

리드는 워커를 띄운 뒤 구현에서 손을 뗀다. 워커가 턴을 끝내면 Desktop 에서는 앱이, 터미널에서는 리드가 띄운 백그라운드 명령의 종료 알림이 리드를 깨운다.

- `mcp__ccd_session__start_session` 이 있으면 Desktop, 없으면(터미널 CLI) 터미널 길을 따른다. 갈리는 곳은 워커 띄우기(2), 보고 읽기와 깨우기(3), CI 읽기와 정리(4)뿐이다.
- 호출됐다는 것이 맡기기로 한 결정이다. 결과물이 코드 변경이 아니면(답만 필요한 조사) 여기서 직접 한다.
- 계획서는 워커의 첫 지시문에, 결과는 PR 본문에 남는다.

## 1. 계획서

워커마다 `job` 스킬의 계획서를 쓴다. 칸과 쓰는 법은 `${CLAUDE_SKILL_DIR}/../job/SKILL.md` 의 「계획서」 절을 Read 로 읽는다. 리드는 `job` 을 Skill 로 부르지 않는다. 사용자는 워커가 뜨면 자리를 떠나니 띄우기 전에 채운다.

- 요청이 여러 레포에 걸치면 관련 레포의 코드를 읽어 구현할 수 있는지만 판정하고, 레포별 목표로 나눈다. 한 워커의 계획서에는 그 레포의 목표만 담는다. 상세 계획, 설계, 레포 사이의 API 는 리드가 정하지 않는다. 워커가 자기 레포에서 정한다.

## 2. 워커 띄우기

### Desktop

먼저 `mcp__ccd_session_mgmt__list_sessions` `{"linked": true}` 로 같은 작업이 이미 떠 있는지 본다.

`mcp__ccd_session__start_session` 인자:

| 인자 | 값 |
|---|---|
| `initiation` | `"user_asked"` |
| `context` | `"fresh"` |
| `cwd` | 목표가 걸린 레포의 메인 체크아웃. `dirname "$(git -C <그 레포> rev-parse --path-format=absolute --git-common-dir)"` 로 얻는다 |
| `use_worktree` | `true`. 앱이 만든 워크트리만 레포의 신뢰를 물려받는다 |
| `source_branch` | 그 레포의 규칙에서 읽은 base |
| `branch_name`, `name` | 짧은 이름 `[a-z0-9-]`, 24자 이하 |
| `title` | 한글 요약, 60자 이하. 요청에 티켓 키나 이슈 번호가 있으면 붙인다 |
| `background` | 왜 필요한지, 지금까지 정한 것, 제약 (80자 이상) |
| `prompt` | 아래 지시문 |

GitHub 원격이 없는 폴더는 `cwd` 를 그 폴더로, `use_worktree` 를 `false` 로 하고 `source_branch`, `branch_name` 은 넣지 않는다. 커밋과 PR 은 없다. 같은 폴더에는 워커를 하나만 띄운다.

앱이 시작을 거부하는 경우가 둘 있다.

- 다른 세션의 알림으로 시작된 턴: 거부되면 바로 사용자에게 알리고 한마디를 받아 띄운다.
- 예약으로 깨어난 턴: `user_asked` 로 불러도 거부된다. 사람 없이 돌릴 작업은 사용자가 자리에 있을 때 워커를 먼저 띄워 두고, 예약은 떠 있는 워커에 `SendMessage` 를 보내는 데 쓴다.

`prompt` 는 아래뿐이다. 다른 세션이 넘긴 지시문의 `/스킬` 은 Desktop 에서 펼쳐지지 않으므로 슬래시 없이 글로 시킨다.

```markdown
fade:job 스킬로 아래 계획서를 수행한다. 사용자: 없음

<계획서>
```

띄운 뒤 세션 링크를 사용자에게 알리고 턴을 끝낸다. 워커를 떼어 내면(`detach_session`) 리드가 알림을 받지 못하니 붙여 둔다.

### 터미널

먼저 `git -C <메인 체크아웃> worktree list` 와 `ListAgents` 로 같은 작업이 이미 떠 있는지 본다. `<메인 체크아웃>` 은 Desktop 의 `cwd` 와 같게 얻는다.

워크트리를 만든다. 브랜치와 이름은 Desktop 의 `branch_name`, `name` 과 같게 짓는다.

```bash
git -C <메인 체크아웃> fetch origin <base>
git -C <메인 체크아웃> worktree add --no-track -b <브랜치> <메인 체크아웃>/.claude/worktrees/<이름> origin/<base>
```

워크트리 안에서 워커를 띄운다. Bash 를 `run_in_background: true`, `timeout: 7200000` 으로 부른다. 이 명령이 끝나는 것이 워커가 끝났다는 알림이다.

```bash
cd <워크트리> && claude -p "<지시문>" \
  --session-id <uuid> -n <이름> \
  --output-format json \
  --permission-mode auto \
  --settings '{"crossSessionInbound":"accept"}' \
  > /tmp/fade-<이름>.json
```

| 플래그 | 이유 |
|---|---|
| `--session-id` | `uuidgen` 으로 미리 정한다. 워커가 끝나기 전에 세션 ID 를 사용자에게 알린다 |
| `-n` | `ListAgents` 에 이 이름으로 나온다 |
| `--output-format json` | 끝나면 `result`(보고 전문)와 `session_id` 를 준다 |
| `--permission-mode auto` | 권한 모드가 없는 `-p` 는 승인이 필요한 호출을 거부한다. 지켜보는 사람이 없다 |
| `--settings` | 지켜보는 사람 없이 세션 간 메시지를 받는다 |

- `--bare` 는 쓰지 않는다. 세션 간 메시지를 받는 통로가 안 열리고, 메모리와 `CLAUDE.md` 도 읽지 않는다.
- `<지시문>` 과 GitHub 원격이 없는 폴더의 규칙은 Desktop 과 같다. 원격이 없으면 워크트리를 만들지 않고 그 폴더에서 띄운다.

띄운 뒤 세션 ID 와 넘겨받는 명령을 사용자에게 알리고 턴을 끝낸다. `-p` 로 만든 세션은 세션 목록에 안 나오니 둘 다 꼭 적는다.

```bash
cd <워크트리> && claude --resume <session_id>
```

- 사용자는 워커가 끝난 뒤에 넘겨받는다. 같은 세션을 두 곳에서 동시에 이으면 기록이 섞인다.
- 워커가 도는 중에 할 말은 리드가 `SendMessage`(`to` = `ListAgents` 에 나온 워커 이름)로 보낸다.

## 3. 워커가 턴을 끝내면

보고 전문을 읽고, 그 응답에서 바로 사용자에게 옮긴다.

| | 보고 전문 | 워커에 답하기 |
|---|---|---|
| Desktop | 알림은 보고의 앞 400자만 준다. `list_events` 로 읽는다 | `SendMessage`(`to` = 워커 세션 id) |
| 터미널 | 출력 파일의 `result` 를 읽는다. `jq -r .result /tmp/fade-<이름>.json` | 워커가 끝났으면 `claude -p --resume <session_id> "<답>"` 을 2절과 같은 플래그로 다시 백그라운드로 띄운다(`--session-id` 는 빼고). 도는 중이면 `SendMessage` |

- 결정할 것을 앞에 두고, 워커가 사용자에게 묻는 것(선택지, 확인 요청)은 번호째 전부 옮긴다.
- 워커의 질문에 답하기 전에 `list_events` 로 사용자가 워커 세션에서 이미 답했는지 본다. 터미널에서는 리드의 명령이 끝났는데 `ListAgents` 에 워커가 보이면 사용자가 넘겨받은 것이다. 그때는 `--resume` 하지 않고 `SendMessage` 로 보낸다.
- 계획서와 이 대화에 근거가 있는 질문은 리드가 위 표대로 답하고 사용자에게 한 줄로 알린다. 새 판단이 필요하면 워커가 쓴 근거째 사용자에게 옮긴다.
- 리드에서 막힌 일은 워커가 아니라 사용자에게 돌린다.

## 4. 완료 판단

워커가 보고에 붙인 원본 증거(명령 출력, 화면 캡처의 절대 경로, 로그)를 완료 기준과 하나씩 대조한다. 증거가 없거나 기준과 맞지 않는 기준은 사용자에게 보고한다. `gh pr diff` 는 사용자가 묻거나 반문할 때만 본다. CI 는 `mcp__ccd_pr__get_status`(`session_id` = 워커 세션 id)로, 터미널에서는 `gh pr checks <PR>` 로 읽는다.

증거를 낼 수단이 그 레포에 없으면 「이 레포에는 증명할 수단이 없다」고 사용자에게 보고만 하고, 수단을 만들지 않는다.

PR 이 병합된 뒤 워커 세션을 보관한다(`archive_session`). 터미널에서는 워크트리를 지운다(`git -C <메인 체크아웃> worktree remove <워크트리>`).
