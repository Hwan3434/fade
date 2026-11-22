# fade

[한국어](README.md) · [日本語](README.ja.md) · [中文](README.zh.md)

A skill plugin for Claude Code only.
What a repo should do (static checks, hooks, lint, tests, verification tools) is left to the repo; the plugin holds only how a lead and its workers work on top of that.
The goal is to delete lines as models get smarter until there are zero, hence the name fade. Why it is built this way is in [WHY.md](WHY.md) (Korean).

## What it does not contain

- Checks, hooks, lint rules. Guarding a repo is the job of that repo's checks. Only a hook a skill needs for its own behavior lives with the skill (`nonstop`).
- Skills that write down principles as prose.
- Values tied to a repo (base branch, merge method, verification tools). The AI running in that repo reads the repo and decides.
- Verification skills (`verify-<repo>`) and static checks. The repo's developers build them. The model to follow is [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example).

## Assumptions

These skills were trimmed on the assumption that the repo already has static checks, hooks, lint, and tests. Use them only in repos where those are good.

The text removed from the skills, and the repo check that takes its place:

| Skill | Removed text | Check the repo must have |
|---|---|---|
| `nonstop` | Do not merge PRs, push directly to the default branch, or force-push | A permission setting or hook that requires confirmation for those commands, and branch protection on the remote |
| `nonstop` | Do not edit protected paths | A hook that blocks edits to protected paths |
| `nonstop` | Do not delete worktrees or branches | A permission setting or hook that requires confirmation for delete commands |
| `nonstop` | Do not run on devices or simulators, or deploy | A permission setting or hook that requires confirmation for run and deploy commands |
| `dispatch` | Branch name format and choosing the base | A check on branch names, and the repo's `CLAUDE.md` |
| `dispatch` | Merge command and merge method | A merge guard that enforces the merge method |
| `dispatch` | Merge and delete only with approval that quotes the user's words | A hook that requires confirmation for merge and branch delete commands |
| `job` | Never break the plan's prohibitions | A permission setting or hook that blocks the prohibited commands |
| `debug` | Per-repo ways to reproduce | A verification skill (`verify-<repo>`) |

`nonstop` guards an unattended session only by refusing what the repo requires confirmation for. In a repo without the four checks above, nothing stops those actions.

## Install

The repo is private, so you need a GitHub account that can read it.

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

To test while editing, load the cloned folder directly.

```bash
claude --plugin-dir ~/workspace/fade
```

Claude cloud sessions do not load plugins. For a repo used in the cloud, put a copy of the skill folders in `.claude/skills/`. In the copy, invocation names lose the `fade:` prefix, and the `nonstop` hook path must be changed to `"${CLAUDE_PROJECT_DIR}"/.claude/skills/nonstop/nonstop.py`.

## Skills

`job` is the smallest unit of work. `dispatch` and `nonstop` work through `job`. `grill` is a standalone tool that sits in no sequence; anyone calls it when decisions remain.

| Skill | What it does | How to invoke |
|---|---|---|
| `job` | The smallest unit of work. Takes one plan (goal, done criteria, what a human checks, materials, special notes, user present/absent) and carries it through planning, implementation, verification, commit, PR, and a report with evidence. Runs in any session | `/fade:job`, or Claude when it receives the text "Carry out the plan below with the fade:job skill" |
| `grill` | Asks about every remaining decision to the end, numbering each question and attaching a recommended answer | `/fade:grill`, or Claude when needed |
| `dispatch` | Hands a code change, as a `job` plan, to a new session (a worker) running in a worktree of the target repo, relays its reports, and checks the evidence the worker attached against the done criteria. If the request spans several repos, starts a separate worker per repo. Works only in Claude Desktop | `/fade:dispatch`, or Claude when needed |
| `debug` | Builds a failing command first, then diagnoses the bug in six steps | `/fade:debug`, or Claude when needed |
| `nonstop` | Works through a task list to the end with nobody watching. Carries out each task with `job`. While tasks remain, hooks block ending the turn, the question tool, and permission prompts | `/fade:nonstop`, by the user directly |

If `nonstop` is invoked in plan mode, it stops at the plan approval prompt. To run unattended, invoke it in another permission mode.

Claude Desktop does not expand a `/skill` in a prompt handed over by another session (confirmed 2026-11-20). So `dispatch` tells the worker in prose, without a slash, "Carry out the plan below with the fade:job skill. User: absent", and the worker's Claude invokes `job` itself. For the same reason workers do not run under `nonstop`.

## Reason for each line

For each line of the skills, this records the failure that line prevents. Only reasons with a source are written. There are two sources: the contracts of the tasks that built and changed this plugin, and the README of the original plugin this one started from. Cells without a source are left empty. A line with an empty cell gets filled when a failure is confirmed, or deleted if the model manages without it.

| Skill | Line | Failure it prevents | Source |
|---|---|---|---|
| `grill` | Ask every question answerable now at once; ask questions that depend on earlier answers in the next round | | |
| `grill` | Number each question and attach a recommended answer | | |
| `grill` | Look up facts findable in the repo, docs, or tools yourself | | |
| `grill` | After answers arrive, ask the newly opened questions | | |
| `grill` | Show a summary of what was decided, and act only after the user confirms it | | |
| `debug` | 1. Build one failing command | | |
| `debug` | 2. Reduce the reproduction conditions | | |
| `debug` | 3. Form 3–5 hypotheses with predictions | | |
| `debug` | 4. Check predictions one at a time; give debug logs a unique prefix | | |
| `debug` | 5. Write a regression test, then fix | | |
| `debug` | 6. Remove debug logs and temp files; record the hypothesis that held | | |
| `debug` | Mask secret values as `<REDACTED>` | | |
| `job` | The plan's fields are goal, done criteria, what a human checks, materials, special notes, and user present/absent | | |
| `job` | Write the done criteria and the evidence to show for each into the plan | The user's words: "Out of 10 tasks, it would do this maybe 1 or 2 times" | Contract |
| `job` | Use the done criteria the user gives as is; if none are given, read the repo, decide them, and get confirmation | | |
| `job` | Put tickets, plans, and decisions into the plan in full | | |
| `job` | Write what the user decided as a category as a category | | |
| `job` | Write constraints specific to this task in the user's own words | | |
| `job` | If "User" is not stated, treat it as present | | |
| `job` | If the goal or done criteria are empty: with the user present, fill them with `grill`; with the user absent, do not start and report the empty fields | | |
| `job` | The "When the user is absent" lines apply only when the user is absent | | |
| `job` | With the user absent, make choices outside the three stop cases yourself and record them in the PR body | | |
| `job` | The plan is the approval of the plan | | |
| `job` | Push and open the PR the plan covers without asking | | |
| `job` | For bug work, follow the order of `debug` | | |
| `job` | Put the result and what needs a decision at the front of the report | The handing session gets only the first 400 characters of the report | Contract |
| `job` | Attach raw evidence for each done criterion | | |
| `job` | Leave it invocable by the model, and write the description so a model receiving "Carry out the plan below with the fade:job skill" picks it | Claude Desktop does not expand a `/skill` in a prompt handed over by another session (confirmed 2026-11-20) | Original README |
| `nonstop` | Write hook command paths with `${CLAUDE_PLUGIN_ROOT}` | Only this variable is filled in hook commands. With any other variable the hook cannot find the script | Contract |
| `nonstop` | Give `nonstop.py` execute permission (`100755`) | The hook runs the script directly, so without the permission the hook does not run | Contract |
| `nonstop` | Use only when the user invokes it directly | | |
| `nonstop` | Handle the task list only through `nonstop.py` | | |
| `nonstop` | Bundle work that depends on each other into one task | | |
| `nonstop` | While waiting on something slow, do the next task first | | |
| `nonstop` | Each time a task settles, set its state to `done`, `hold`, or `blocked` | | |
| `nonstop` | When no tasks remain, give the `show` output verbatim as the final answer | | |
| `nonstop` | Each task gets its own branch and PR, not stacked on the previous task | | |
| `nonstop` | After opening the PR, move on without waiting for CI | | |
| `nonstop` | If the cause was not found, do not fix | | |
| `nonstop` | Refuse what the repo requires confirmation for, and record it as `blocked` | | |
| `nonstop` | Carry out each task with `job` (user absent) | | |
| `nonstop` | When `job` says to stop and ask, record `hold`; also record what `job` chose with `decide` | | |
| `nonstop` | Do not settle irreversible decisions; record them as `hold` | | |
| `nonstop` | When a permission is denied, do not retry in another form | | |
| `nonstop` | While tasks remain, hooks block ending the turn, the question tool, and permission prompts | | |
| `dispatch` | The lead is the session that invoked this skill, whether opened in a repo or in a parent folder | | |
| `dispatch` | If `start_session` is missing, stop and say so | | |
| `dispatch` | Research that only needs an answer is done directly, not handed off | | |
| `dispatch` | If the request spans several repos, judge only feasibility, and write a separate plan per repo | | |
| `dispatch` | Detailed plans, design, and APIs between repos are decided by the worker in its own repo | | |
| `dispatch` | Fill in the plan before starting the worker | | |
| `dispatch` | First check whether the same task is already running | | |
| `dispatch` | `cwd` is the main checkout of the target repo | | |
| `dispatch` | `use_worktree` is `true` | | |
| `dispatch` | For a folder without a GitHub remote: `use_worktree: false`, no commits or PRs, one worker per folder | | |
| `dispatch` | List the two cases where the app refuses to start a session | In a turn started by another session, the app refuses to start a session | Contract |
| `dispatch` | The worker prompt tells it to use `job` in prose, without a slash | Claude Desktop does not expand a `/skill` in a prompt handed over by another session, so a worker cannot run under `nonstop` (confirmed 2026-11-20) | Original README |
| `dispatch` | Do not detach the worker | | |
| `dispatch` | Read the full report with `list_events` | A notification carries only the first 400 characters of the report | Contract |
| `dispatch` | Before answering a worker's question, check whether the user already answered | | |
| `dispatch` | The lead answers questions it has grounds for, and relays new judgments to the user | | |
| `dispatch` | Turn work blocked at the lead back to the user | | |
| `dispatch` | Judge completion by checking the worker's raw evidence against the done criteria; read `gh pr diff` only when the user asks | | |
| `dispatch` | If the repo has no means to prove it, only report that, and do not build the means | | |
| `dispatch` | Archive the worker session after its PR is merged | | |

## Criteria for adding a skill

- Add only what several repos use with the same text. A skill used in one repo lives in that repo.
- Add or change something only when a failure happened in a real session.
- Write down the process. Rules a check can enforce go to the repo's checks.
- Do not write repo-bound values.
- Delete lines that describe what the model does anyway.
- Write the text for Claude Code only. Other AIs are not considered.

## References

- [mattpocock/skills](https://github.com/mattpocock/skills): `grill` started from `grilling`, `debug` from `diagnosing-bugs`.
- `pstack` in [cursor/plugins](https://github.com/cursor/plugins): the approach of shipping no checks and writing for a single tool.
- [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example): the model for verification skills.
