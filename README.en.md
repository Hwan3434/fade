# fade

[한국어](README.md) · [日本語](README.ja.md) · [中文](README.zh.md)

A set of skills that does not depend on any one agent. It is currently distributed as a Claude Code plugin. It was not built to gain features; it was built to shrink.
The goal is to delete lines as models get smarter until none are left, hence the name fade.

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
- Even a rule that prose could enforce is taken out of the skills when a check can enforce it, and sent to the repo's checks instead. What stays in the skills is process alone.
- So it only works well in repos that have those checks. `nonstop`, which runs with no one watching, stops only by refusing actions the repo asks to confirm; in a repo without such checks, nothing stops those actions.
- Values that differ per repo (base branch, merge method, how to verify) are not written down. The model running in that repo reads the repo and decides.
- A line is added only when the failure it prevents has been seen in a real session. Lines describing what the model already does are deleted.
- Only what is used with the same text across many repos goes in. The text names no agent-specific tools or mechanisms; it states only the conditions to meet. How to meet them is up to the environment that uses it.

## Where it is going

- With every new model, try deleting lines one by one. If the model does the job without a line, that line does not come back.
- Lines are added only when a failure is confirmed. Even added lines are future candidates for deletion.
- When the skills disappear one by one and the last line is deleted, that is when this plugin is finished.

## Skills

- `job`: the smallest unit of work. Takes one plan and carries it through planning, implementation, verification, commit, PR, and a report with evidence attached.
- `grill`: asks about every decision left before execution, numbered and with a recommended answer, until none remain.
- `dispatch`: hands a code change to a new session (a worker) running in the repo's worktree as a `job` plan, and checks the worker's evidence against the done criteria.
- `debug`: starts by building one failing command, then diagnoses the bug in a fixed order.
- `nonstop`: works through a task list to the end with no one watching, running each task as a `job`. Only for when the user invokes it directly.

## Install

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

Claude cloud sessions do not load plugins. For a repo used in the cloud, put a copy of the skill folders in `.claude/skills/`.

## Credits

- [mattpocock/skills](https://github.com/mattpocock/skills): `grill` started from `grilling`, and `debug` from `diagnosing-bugs`.
- `pstack` in [cursor/plugins](https://github.com/cursor/plugins): the approach of shipping no checks.
- [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example): the model for verification skills.

## License

[MIT](LICENSE)
