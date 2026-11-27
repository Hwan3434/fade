# fade

[한국어](README.md) · [日本語](README.ja.md) · [中文](README.zh.md)

A skill plugin for Claude Code only. It is used in the Claude desktop app (Code tab) and the Claude CLI. If you use another agent, read the skills and adapt them to your environment. It was not built to gain features; it was built to shrink.
The goal is to delete prose as models get smarter until no lines are left, hence the name fade. What shrinks is the prose. The structure that guards the process (scripts, hooks, tests) stays.

## Why it exists

### The ultimate goal

> Ultimately, I hope for the day this skill is no longer needed. The whole point of minimizing is to wait for the day AI is smart enough that nothing needs explaining, and on the premise that AI has become smart, we are practicing the art of taking things away.

### What trusting AI means

> What it means to trust AI changes every day, with every new model. But trusting AI means keeping explanations to it minimal; it does not mean skipping static checks, hooks, lint, or tests. Those are essential, and on top of them, whether the agent goes forward or back, turns right or left, we trust it.

### Where this tool sits

> If we can't build something properly, let's not build it for them; let the developers build it. We are a tool for steering AI on top of what those developers have built. We stay out of the static-check layer.

### The road not taken

> Trying to control agents with prose. That is the heart of it.

## How it is built

- Guarding a repo (static checks, hooks, lint, tests, verification tools) is that repo's job. fade holds only how a lead and its workers work on top of it.
- That way of working is also guarded by structure rather than prose. `job`'s stage record is kept by a script (`job.py`) that records only what it confirmed by running the test command itself, and right before a merge a hook checks that record and CI. The only structure fade ships is fade's own work format, which has nothing to do with any particular repo, and one hook that blocks a few irreversible commands in every session.
- Even a rule that prose could enforce is taken out of the skills when a check can enforce it. It goes first to the repo's checks, and anything that differs per person goes to that person's settings. What stays in the skills is process alone.
- So it only works well in repos that have those checks. `nonstop`, which runs with no one watching, stops only by refusing actions the repo asks to confirm; in a repo without such checks, nothing stops those actions.
- Values that differ per repo or per person (base branch, merge method, branch names, how to verify) are not written down. The repo's rules and the person's settings decide them, and the model reads and follows them.
- A line is added only when the failure it prevents has been seen in a real session. Lines describing what the model already does are deleted.
- Only what is used with the same text across many repos goes in. It also says how to meet the conditions in the Claude desktop app and the CLI.

## Where it is going

- With every new model, try deleting lines one by one. If the model does the job without a line, that line does not come back.
- Lines are added only when a failure is confirmed. Even added lines are future candidates for deletion.
- Structure that is no longer used is deleted too. But a check is not deleted just because models got better.
- When the skills disappear one by one and the last line is deleted, that is when this plugin is finished.

## Skills

- `job`: the smallest unit of work. Takes one plan and carries it through tests first, implementation, evidence, trying it by hand, and code review repeated until no blocking finding is left, then PR, merge, and report. The review always runs the bug axis, and adds the spec axis only when the diff against the base is 200 lines or more. After a fix, only the fixed part is reviewed again, and only the evidence and tries that depend on the changed paths are redone. While review is still running only blocking findings are fixed; minor findings are collected and fixed in one commit once no blocking finding is left, and that commit alone is then checked on the bug axis. Answers from agents such as the reviewer and the tester are waited for without ending the turn. If it cannot solve a problem or needs the user's decision, it stops there and reports. If the user narrows the scope (for example "PR only"), it does only that much.
- `try`: starts the `tester` agent to use the result the way the user would, and leaves screens and logs for each case.
- `harden`: stops a mistake the AI made with a check (lint, test, hook, permission settings) instead of adding prose to the instructions.
- `grill`: asks about every decision left before execution, numbered and with a recommended answer, until none remain.
- `dispatch`: hands a code change to a new session (a worker) running in the repo's worktree as a `job` plan, and checks the worker's evidence against the done criteria. Starts workers with the session tools in the desktop app and with `claude -p` in the CLI. Before starting one, a fresh subagent looks for gaps in the plan; after the worker finishes, it passes `hardener`'s check proposals on to the user. Once the PR is merged or closed, it cleans up the worker's worktree, the merged work branch, and the worker session without asking (it deletes nothing that has uncommitted changes or commits missing from the remote).
- `debug`: starts by building one failing command, then diagnoses the bug in a fixed order.
- `nonstop`: works through a task list to the end with no one watching, running each task as a `job`. Only for when the user invokes it directly.

## Agents

Subagents that the skills start. Their definitions are in `agents/`.

- `reviewer`: the spec-axis reviewer for `job`. It does not trust the implementer's report; it checks the plan against the diff item by item, looking first at whether the spec is met (missing, extra, misunderstood) and then at test quality. Each finding is marked blocking or minor. Its tools are read-only (Read, Grep, Glob).
- `tester`: uses the result the way a user would and only reports. It writes scenarios first and leaves screens and output under `fade-try/` in the worktree's git directory. Its editing tools (Edit, Write, NotebookEdit) are removed.
- `hardener`: groups the mistakes of finished work in the mistake log by key, and when the same key shows up twice or more, or the mistake could happen to anyone, proposes a check in `harden`'s order. It only proposes and does not fix.

## Structure

- `skills/job/job.py`: `job`'s stage record. A failure before implementation (red) and a pass after it (green) are recorded only after running the command itself. Evidence and hands-on tries are recorded only with files. For the merge, green and review count only when taken at the current commit. Evidence and tries recorded with the paths they depend on (`--paths`) stay valid as long as those paths have not changed since the commit they were taken at; without paths they count only at the current commit. `review-files` reports the line count of the diff against the base and which review axes to run, and from the second review on it writes only the part fixed since the last commit the spec reviewer saw. `review --minor` records the bug-axis review of the single commit that fixes the collected minor findings, and it counts as the review the merge conditions require. Options of `start`, `review`, and `show` are read whether they come before or after the other arguments, and an unknown option is rejected by every command. A merge also needs a reversibility record (`door`); if it is a one-way door (cannot be undone), the user decides the merge. The first line of `show` is the status, and its default output is one line per completion criterion. Full commands and logs appear with `show --full`. The record lives in the worktree's git directory and is never committed.
- `hooks/merge_gate.py`: right before `gh pr merge`, checks that worktree's `job` record, CI, and whether the PR's latest commit is the local HEAD that was verified. If something is missing, or the job was "PR only", it blocks the merge, says why, and writes it to the mistake log. Where there is no `job` record it does nothing. It is a guard rail against mistakes, not a security boundary.
- `hooks/permission_gate.py`: in an unattended `job` (`job.py start --unattended`), when a permission prompt is about to appear it denies it instead of waiting. If the blocked step is essential to a completion criterion the job reports where it was blocked and ends; if it is a side step, the job drops that step and carries on. Each denial is written to the mistake log. In any other session it does nothing.
- `hooks/destructive_gate.py`: **runs on every Bash call in every session where fade is installed.** It is the only fade hook that changes a session's behavior regardless of `job`. It denies recursive deletion of the root, your home or any folder above it, or `~/.ssh`; force pushes to the default branch (main, master, or the repo's default branch); `dd` writing to a device; and `mkfs`. Quoted text and heredoc bodies are not treated as commands. It only denies and never allows; if such a command is really needed, the user types it in a terminal. To turn it off, disable the fade plugin.
- Mistake log `~/.claude/fade/mistakes.jsonl`: one line per mistake, collected across repos and jobs. It is written when the merge hook or the permission hook blocks something, by `job.py stop`, and by `job.py slip` (blocking review findings that were fixed, CI failures, mistakes the user points out). `hardener` fills in the key and handling. The `FADE_MISTAKES` environment variable changes the path.
- `tests/`: tests for the scripts and hooks above, the agent definitions, and `nonstop.py`, run by GitHub Actions on every PR.

## Install

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

The desktop app reads the same settings, so installing once from the CLI makes it available in both. Claude cloud sessions do not load plugins. For a repo used in the cloud, put a copy of the skill folders in `.claude/skills/`.

## Credits

- [mattpocock/skills](https://github.com/mattpocock/skills): `grill` started from `grilling`, and `debug` from `diagnosing-bugs`. The spec axis of `code-review` became `reviewer`'s spec check, `tdd`'s test rules (expected values as independent constants, never mocking your own module) became `reviewer`'s test-quality check, `retro` became `hardener`, and the Merge Danger section of `pr` (one-way or two-way door, blast radius) became `job.py door`.
- [obra/superpowers](https://github.com/obra/superpowers): the reviewer in `subagent-driven-development` (does not trust the implementer's report and checks the diff) became `reviewer`, and the builder check in `brainstorming` became `dispatch`'s plan gap check.
- [garrytan/gstack](https://github.com/garrytan/gstack): `careful` became the destructive command hook, `qa-only` became `tester`, and the PR commit check in `land-and-deploy` became part of the merge hook.
- `pstack` in [cursor/plugins](https://github.com/cursor/plugins): the approach of shipping no checks.
- [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example): the model for verification skills.

## License

[MIT](LICENSE)
