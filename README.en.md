# fade

[한국어](README.md)

A plugin for Claude Code only. It holds the way a lead and its workers work, from test-first through merge, and the record script and hooks that guard that way of working. It was not built to gain features; it was built to shrink.

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

## Where it is used

| | |
|---|---|
| Agent | Claude Code only. If you use another agent, read the skills and adapt them |
| App | Not fixed. Terminal or app, it is the same wherever Claude Code runs |
| Install | Once, into a person's Claude Code. A repo holds no files for fade |
| Run | Local only. Cloud sessions do not load plugins, so neither lead nor worker runs there |
| OS | macOS and Linux. On Windows the hooks and `job.py` do not run |

## How it is built

- Guarding a repo (static checks, hooks, lint, tests) is that repo's job. fade holds only how a lead and its workers work on top of it.
- That way of working is also guarded by structure rather than prose. `job.py` records only what it confirmed by running the command itself, and right before a merge a hook checks that record and CI.
- A rule that a check can enforce is taken out of the skills and sent to a check. The repo's checks come first, and what differs per person belongs to that person's settings.
- Values that differ per repo or per person (base branch, merge method, branch names, model) are not written down. The repo's rules and the person's settings decide them.
- Adding a line requires a failure it prevents, confirmed in a real session. The same goes for hooks.
- The hooks are a guardrail against mistakes, not a security boundary. They do not catch commands hidden in `bash -c` or a script, and do not try to.
- It only works properly in a repo that has its checks in place.

## Where it is going

- With every new model, try deleting one line. If the model manages without it, the line does not come back.
- Lines are added only when a failure has been confirmed. An added line is still a candidate for deletion someday.
- Structure is deleted too once it is no longer used. But a check is never deleted just because models got better.
- When the last line is gone, that is when this plugin is finished.

## Skills

| Skill | What it does |
|---|---|
| `job` | The smallest unit of work. Takes one plan and carries it through test-first, implementation, evidence, trying it by hand, code review, PR, merge, and report. If you narrow the scope ("up to the PR only"), it does only that much |
| `dispatch` | Hands a code change to a new session (a worker) running in a worktree of that repo, and checks the evidence the worker left against the done criteria |
| `nonstop` | Runs a task list to the end with nobody watching, doing a `job` for each task |
| `try` | Uses the result the way a user would and leaves screens and logs |
| `harden` | Blocks a mistake the AI made with a check (lint, test, hook, permission setting) instead of prose in the instructions |
| `debug` | Starts from one failing command and diagnoses a bug in a fixed order |
| `grill` | Asks every remaining decision before execution |

The detailed order is in each skill's `SKILL.md`.

## Agents

Subagents the skills launch. No model is fixed.

| Agent | What it does |
|---|---|
| `reviewer` | Does not trust the implementer's report; checks the plan against the diff. Read-only |
| `tester` | Uses the result like a user and only reports. Does not fix |
| `hardener` | Groups the mistakes of finished work and drafts check proposals. Proposes only |

## Structure

| File | What it guards |
|---|---|
| `skills/job/job.py` | The work record. Test failure and pass are recorded only when confirmed by running the command itself. The record lives in the worktree's git folder, so it is never committed |
| `hooks/merge_gate.py` | Right before a merge, checks that work's record and CI. Blocks if anything is missing |
| `hooks/review_gate.py` | Right before a review is recorded, checks that the review really read the diff to the end |
| `hooks/lead_gate.py` | Keeps a worker from doing the lead's work itself (clearing a human check, the comparison, deleting a merged worktree) |
| `hooks/permission_gate.py` | In work with nobody watching, refuses an approval prompt instead of waiting on it |
| `hooks/destructive_gate.py` | Blocks a few irreversible commands, such as deleting the home folder or force-pushing to the default branch. **The only hook that applies to every session with fade installed** |
| `bin/` | The entry point that lets `job.py` and `nonstop.py` be called without a path |
| `tests/` | Tests for all of the above. Run on every PR |

- The first four judge only in a worktree that has a `job` record. Where `job` is not used, they do nothing.
- If a hook crashes, it does not block and hands over to the normal permission flow.
- What each hook blocks and cannot block is in the header comment of its file. Calling `job.py` with no arguments lists its commands.
- Mistakes pile up in `~/.claude/fade/mistakes.jsonl`. A line is added when a hook blocks and for each finding fixed in review, and `hardener` groups them.

## Install

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

To turn it off, disable the plugin. A single hook cannot be turned off on its own.

## Credits

- [mattpocock/skills](https://github.com/mattpocock/skills): `grill`, `debug`, the `reviewer` criteria, `hardener`, and whether a change can be undone (`job.py door`).
- [obra/superpowers](https://github.com/obra/superpowers): the reviewer that does not trust reports, the blank-spot check on plans.
- [garrytan/gstack](https://github.com/garrytan/gstack): the destructive-command hook, `tester`, checking the PR commit before merge.
- [cursor/plugins](https://github.com/cursor/plugins)' `pstack`, [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example).

## License

[MIT](LICENSE)
