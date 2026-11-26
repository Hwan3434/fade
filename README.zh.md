# fade

[한국어](README.md) · [English](README.en.md) · [日本語](README.ja.md)

只面向 Claude Code 的技能插件，在 Claude 桌面应用（Code 标签页）和 Claude CLI 中使用。使用其他代理（agent）的人，可以读一读技能，按自己的环境改写。它不是为了增加功能而做的，而是为了不断变少而做的。
目标是模型越聪明，就删掉越多的文字，最终归零，所以叫 fade。变少的是文字；守护流程的结构（脚本、钩子、测试）会留下来。

## 为什么做它

### 终极目标

> 归根结底，我希望有一天不再需要这个技能。做减法的目的本身，就是盼着 AI 聪明到无需多加解释的那一天；在 AI 已经变聪明的前提下，我们在践行做减法的美学。

### 信任 AI 意味着什么

> 信任 AI 意味着什么，每天都在变，每出一个新模型就变一次。但信任 AI 是指尽量少向 AI 解释，而不是不做静态检查、钩子、lint 和测试。这些是必需的；在它们之上，无论智能体前进还是后退、右转还是左转，我们都信任它。

### 这个工具的位置

> 做不好的东西就不要替人去做，让开发者自己做。我们是在开发者做好的东西之上控制 AI 的工具，不介入静态检查这一层。

### 放弃的路

> 想用文字去控制智能体。核心就是这一点。

## 怎么做的

- 守护仓库的工作（静态检查、hook、lint、测试、验证手段）由那个仓库负责。fade 只承载在其之上主控（lead）和工作者（worker）的工作方式。
- 这种工作方式也尽量用结构而不是文字来守。`job` 的阶段记录由脚本（`job.py`）保存，它只记录自己亲自运行测试命令确认过的结果；合并之前，钩子会检查这份记录和 CI。fade 附带的结构只有与具体仓库无关的、fade 自己的工作形式，以及一个在所有会话里拦下几种不可逆命令的钩子。
- 即便是能用文字约束的规则，只要能用检查拦住，就从技能里拿掉，交给检查。首先交给那个仓库的检查；因人而异的东西交给那个人自己的设置。技能里只留下流程。
- 所以它只在检查齐全的仓库里才能好好运转。无人值守运行的 `nonstop` 只靠拒绝仓库要求确认的操作来停下；在没有这些检查的仓库里，没有任何东西能拦住那些操作。
- 因仓库、因人而异的值（base 分支、合并方式、分支名、验证方法）不写进来。由那个仓库的规则和那个人的设置决定，模型读取并遵循它们。
- 只有在真实会话中确认出现了某一行要防止的失败，才会加上那一行。描述模型本来就会做的事的行则删掉。
- 只收录在多个仓库中以同样正文使用的内容。也写明在 Claude 桌面应用和 CLI 中如何满足条件。

## 往哪里去

- 每出一个新模型，就试着逐行删除。如果模型没有那一行也能做好，那一行就不会再回来。
- 只有确认出现失败时才会加行。加上的行也终究是将来要删的候选。
- 不再使用的结构也会删掉。但不会仅仅因为模型变好了就删掉检查。
- 当技能一个个消失、最后一行也被删掉时，就是这个插件完成的时候。

## 技能

- `job`：工作的最小单位。接收一份计划书，先写测试，再实现、留证据、亲手试用，反复做代码审查（bug 轴和规格轴）直到没有阻断性意见，再提 PR、合并、报告。遇到解决不了的问题或需要用户决定时，就在那里停下并报告。用户若缩小范围（比如“只到 PR”），就只做到那一步。
- `try`：启动 `tester` 代理，按用户实际使用的方式试用成果，并按每种情况留下画面和日志。
- `harden`：不往指示里加文字，而是用检查（lint、测试、钩子、权限设置）拦住 AI 犯过的错。
- `grill`：在执行前把剩下的决定逐一追问到底，每个问题都带编号和推荐答案。
- `dispatch`：把代码改动以 `job` 计划书的形式交给在仓库 worktree 中运行的新会话（工作者），并将工作者附上的证据与完成标准对照。在桌面应用中用会话工具启动，在 CLI 中用 `claude -p` 启动。启动前先让一个新的子代理找出计划书的空缺；工作者结束后，把 `hardener` 的检查建议转告用户。
- `debug`：先做出一条会失败的命令，再按固定顺序诊断 bug。
- `nonstop`：无人值守地把任务列表跑到底，每个任务都以 `job` 执行。只在用户亲自调用时使用。

## 代理

由技能启动的子代理，定义在 `agents/` 里。

- `reviewer`：`job` 的规格轴审查者。不相信实现者的报告，把计划书和 diff 逐条对照，先看是否满足规格（遗漏、多做、理解错），再看测试质量。每条意见都标明是阻断性意见还是次要意见。工具只有读取（Read、Grep、Glob）。
- `tester`：像用户一样试用成果，只做报告。先写场景，画面和输出留在 worktree 的 git 目录中的 `fade-try/` 里。没有修改文件的工具。
- `hardener`：把已完成工作的失误在失误记录里按 key 归类；同一个 key 出现两次以上，或是谁都可能犯的失误，就按 `harden` 的顺序提出检查建议。只提建议，不动手修改。

## 结构

- `skills/job/job.py`：`job` 的阶段记录。实现前的失败（red）和实现后的通过（green）只有在亲自运行命令确认后才会记录；证据和亲手试用只有附上文件才会记录。合并条件中的 green、证据、试用和审查只认在当前提交上取得的，所以一旦有修正提交就要重做。必须记下能否撤回（`door`）才能合并；如果是单向门（无法撤回），由用户决定是否合并。`show` 的第一行是状态。记录放在 worktree 的 git 目录里，不会被提交。
- `hooks/merge_gate.py`：在 `gh pr merge` 之前检查该 worktree 的 `job` 记录、CI，以及 PR 的最新提交是否就是验证过的本地 HEAD。若有缺漏，或这次工作“只到 PR”，就拦下合并、说明原因，并写进失误记录。没有 `job` 记录的地方什么也不做。它是防止失误的护栏，不是安全边界。
- `hooks/permission_gate.py`：在无人值守的 `job`（`job.py start --unattended`）里，权限确认框将要弹出时不等待，直接拒绝。工作会报告卡住的地方后结束。每次拒绝都会写进失误记录。其他会话里什么也不做。
- `hooks/destructive_gate.py`：**作用于所有安装了 fade 的会话中的每一次 Bash 调用。** 这是 fade 里唯一与 `job` 无关、会改变会话行为的钩子。它拒绝递归删除根目录、主目录及其上层目录、`~/.ssh`，拒绝向默认分支（main、master 或该仓库的默认分支）force push，拒绝向设备写入的 `dd` 和 `mkfs`。被引号括起的文字和 heredoc 正文不当作命令。它只拒绝、不放行；真正需要的命令由用户在终端里亲自输入。想关掉它就停用 fade 插件。
- 失误记录 `~/.claude/fade/mistakes.jsonl`：跨仓库、跨工作汇集的失误，一行一条。合并钩子和权限确认钩子拦下时、`job.py stop`、`job.py slip`（审查中修好的阻断性意见、CI 失败、用户指出的失误）都会写入，`hardener` 负责填写 key 和处理情况。可以用环境变量 `FADE_MISTAKES` 改路径。
- `tests/`：上面的脚本和钩子、代理定义以及 `nonstop.py` 的测试，每个 PR 都由 GitHub Actions 运行。

## 安装

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

桌面应用读取同样的设置，所以用 CLI 安装一次，两边都能用。Claude 云端会话不会读取插件。要在云端使用的仓库，把技能文件夹的副本放进 `.claude/skills/`。

## 参考

- [mattpocock/skills](https://github.com/mattpocock/skills)：`grill` 源自 `grilling`，`debug` 源自 `diagnosing-bugs`。`code-review` 的规格轴成了 `reviewer` 的规格检查，`tdd` 的测试准则（预期值用独立常量，不 mock 自己的模块）成了 `reviewer` 的测试质量检查，`retro` 成了 `hardener`，`pr` 的 Merge Danger（单向门还是双向门、影响范围）成了 `job.py door`。
- [obra/superpowers](https://github.com/obra/superpowers)：`subagent-driven-development` 里的审查者（不相信实现者的报告，用 diff 核实）成了 `reviewer`，`brainstorming` 的 builder check 成了 `dispatch` 的计划书空缺检查。
- [garrytan/gstack](https://github.com/garrytan/gstack)：`careful` 成了拦截破坏性命令的钩子，`qa-only` 成了 `tester`，`land-and-deploy` 的 PR 提交核对成了合并钩子的一部分。
- [cursor/plugins](https://github.com/cursor/plugins) 中的 `pstack`：不附带检查的方式。
- [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example)：验证技能的范例。

## 许可证

[MIT](LICENSE)
