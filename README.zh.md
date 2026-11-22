# fade

[한국어](README.md) · [English](README.en.md) · [日本語](README.ja.md)

仅供 Claude Code 使用的技能插件。
仓库该做的事(静态检查、hook、lint、测试、验证手段)交给仓库,插件只处理在此之上主控(lead)与工作者(worker)的工作方式。
目标是随着模型越来越聪明不断删减行数,最终删到 0 行,所以叫 fade。为什么这样做,见 [WHY.md](WHY.md)(韩文)。

## 不包含的内容

- 检查、hook、lint 规则。守护仓库是该仓库检查的职责。只有技能自身运行所需的 hook 与技能放在一起(`nonstop`)。
- 用文字写下原则的技能。
- 与仓库绑定的值(base 分支、合并方式、验证手段)。由在该仓库中运行的 AI 读取仓库后判断。
- 验证技能(`verify-<仓库>`)与静态检查。由该仓库的开发者来做。范例是 [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example)。

## 前提

这些技能假定仓库已具备静态检查、hook、lint 和测试,因此删减了文字。只在这些做得好的仓库中使用。

从技能中删去的文字,以及接替其职责的仓库检查如下。

| 技能 | 删去的文字 | 仓库应具备的检查 |
|---|---|---|
| `nonstop` | 不合并 PR、不直接 push 到默认分支、不强制 push | 对这些命令要求确认的权限设置或 hook,以及远端的分支保护 |
| `nonstop` | 不修改受保护路径 | 阻止修改受保护路径的 hook |
| `nonstop` | 不删除工作树和分支 | 对删除命令要求确认的权限设置或 hook |
| `nonstop` | 不在真机或模拟器上运行,不部署 | 对运行和部署命令要求确认的权限设置或 hook |
| `dispatch` | 分支命名格式与 base 的选择 | 检查分支名的检查,以及仓库的 `CLAUDE.md` |
| `dispatch` | 合并命令与合并方式 | 强制合并方式的合并守卫 |
| `dispatch` | 只有在引用了用户原话的批准时才合并和删除 | 对合并命令和分支删除命令要求确认的 hook |
| `dispatch` | 不违反契约中的禁止事项 | 阻止被禁止命令的权限设置或 hook |
| `debug` | 各仓库不同的复现方法 | 验证技能(`verify-<仓库>`) |

`nonstop` 只通过拒绝仓库要求确认的操作来守护无人值守的会话。在没有上面四行检查的仓库里,没有任何东西能阻止这些操作。

## 安装

这是私有仓库,需要能读取该仓库的 GitHub 账号。

```bash
claude plugin marketplace add Hwan3434/fade
```

```bash
claude plugin install fade@fade
```

边改边试时,直接加载克隆下来的文件夹。

```bash
claude --plugin-dir ~/workspace/fade
```

Claude 云端会话不加载插件。要在云端使用的仓库,把技能文件夹的副本放进 `.claude/skills/`。副本中调用名不带 `fade:` 前缀,并且要把 `nonstop` 的 hook 路径改为 `"${CLAUDE_PROJECT_DIR}"/.claude/skills/nonstop/nonstop.py`。

## 技能

| 技能 | 作用 | 调用方式 |
|---|---|---|
| `grill` | 给每个问题编号并附上推荐答案,把剩下的决定一直问到底 | `/fade:grill`,或由 Claude 在需要时调用 |
| `dispatch` | 把代码变更任务交给在目标仓库工作树中运行的新会话(工作者),转达其报告,并把工作者附上的证据与完成标准对照。请求跨多个仓库时,每个仓库单独启动一个工作者。仅在 Claude Desktop 中可用 | `/fade:dispatch`,或由 Claude 在需要时调用 |
| `debug` | 先做出一个会失败的命令,再分六步诊断 bug | `/fade:debug`,或由 Claude 在需要时调用 |
| `nonstop` | 在无人看守的情况下把任务列表做到底。仍有剩余任务时,由 hook 阻止结束回合、提问工具和权限弹窗 | 由用户直接用 `/fade:nonstop` 调用 |

在计划模式下调用 `nonstop`,会停在计划批准弹窗。无人值守运行时,请在其他权限模式下调用。

`dispatch` 启动的工作者不会以 `nonstop` 运行。Claude Desktop 不会展开其他会话传来的指令中的 `/技能`(2026-11-20 确认)。所以工作者的指令用文字授予权限。

## 每一行的依据

为技能的每一行写下它所防止的失败。只写有出处的依据。出处有两个:构建本插件那次任务的契约,以及本插件起步时所基于的原插件的 README。没有出处的格子留空。空格对应的行,在确认出现失败时补上,或在模型没有它也能做好时删掉。

| 技能 | 行 | 防止的失败 | 出处 |
|---|---|---|---|
| `grill` | 现在能回答的问题一次问完,依赖前面答案的问题下一轮再问 | | |
| `grill` | 每个问题附上编号和推荐答案 | | |
| `grill` | 能在仓库、文档、工具中查到的事实自己去查 | | |
| `grill` | 收到回答后,再问新出现的问题 | | |
| `grill` | 把定下来的内容整理给用户看,用户确认后再执行 | | |
| `debug` | 1. 做出一个会失败的命令 | | |
| `debug` | 2. 缩小复现条件 | | |
| `debug` | 3. 提出 3~5 个假设并附上预测 | | |
| `debug` | 4. 逐个验证预测,调试日志加上唯一前缀 | | |
| `debug` | 5. 先写回归测试再修复 | | |
| `debug` | 6. 删除调试日志和临时文件,记下成立的假设 | | |
| `debug` | 机密值用 `<REDACTED>` 遮住 | | |
| `nonstop` | hook 命令的路径用 `${CLAUDE_PLUGIN_ROOT}` 写 | 在 hook 命令中只有这个变量会被填入。用别的变量,hook 就找不到脚本 | 契约 |
| `nonstop` | 给 `nonstop.py` 执行权限(`100755`) | hook 直接执行脚本,没有权限 hook 就不会运行 | 契约 |
| `nonstop` | 只在用户直接调用时使用 | | |
| `nonstop` | 任务列表只通过 `nonstop.py` 处理 | | |
| `nonstop` | 相互依赖的工作合并成一个任务 | | |
| `nonstop` | 等待耗时的事情时先做下一个任务 | | |
| `nonstop` | 每个任务有结果时,把状态改为 `done`、`hold` 或 `blocked` | | |
| `nonstop` | 没有剩余任务时,把 `show` 的输出原样作为最后的回答 | | |
| `nonstop` | 每个任务有自己的分支和 PR,不叠在前一个任务之上 | | |
| `nonstop` | 提交 PR 后不等 CI,直接进入下一个任务 | | |
| `nonstop` | 没找到原因就不修 | | |
| `nonstop` | 拒绝仓库要求确认的操作,并记为 `blocked` | | |
| `nonstop` | 可撤回的决定按推荐方案定下,用 `decide` 记录 | | |
| `nonstop` | 不可撤回的决定不做,记为 `hold` | | |
| `nonstop` | 权限被拒后,不换个形式重试 | | |
| `nonstop` | 仍有剩余任务时,由 hook 阻止结束回合、提问工具和权限弹窗 | | |
| `dispatch` | 主控是调用本技能的会话。无论在哪个仓库打开,还是在上层文件夹打开,都一样 | | |
| `dispatch` | 没有 `start_session` 时停下并告知 | | |
| `dispatch` | 只需要答案的调查不交出去,自己做 | | |
| `dispatch` | 没有目的或还有待定的决定时,先用 `grill` 定下再启动 | | |
| `dispatch` | 跨多个仓库时只判断能否实现,并为每个仓库单独写契约 | | |
| `dispatch` | 详细计划、设计、仓库之间的 API 由工作者在自己的仓库中决定 | | |
| `dispatch` | 在启动工作者之前定下完成标准和要展示的运行结果 | 没有这一行,启动前定下完成标准的情况十次里只会发生一两次(用户的估计) | 契约 |
| `dispatch` | 修 bug 时,放入修复前会失败的复现测试 | | |
| `dispatch` | 工单、计划书、决定事项把内容整个放进指令 | | |
| `dispatch` | 用户按类别定下的内容按类别写 | | |
| `dispatch` | 只针对本次任务的约束,照用户原话写 | | |
| `dispatch` | 先看同样的任务是否已经在运行 | | |
| `dispatch` | `cwd` 是目标仓库的主检出 | | |
| `dispatch` | `use_worktree` 为 `true` | | |
| `dispatch` | 没有 GitHub 远端的文件夹:`use_worktree: false`,不提交、不开 PR,每个文件夹只启动一个工作者 | | |
| `dispatch` | 写下应用拒绝启动会话的两种情况 | 在其他会话发起的回合中,应用会拒绝启动会话 | 契约 |
| `dispatch` | 工作者的指令用文字授予权限 | Claude Desktop 不会展开其他会话传来的指令中的 `/技能`,所以工作者无法以 `nonstop` 运行(2026-11-20 确认) | 原 README |
| `dispatch` | 不把工作者分离 | | |
| `dispatch` | 用 `list_events` 读取报告全文 | 通知里只有报告的前 400 个字符 | 契约 |
| `dispatch` | 回答工作者的问题之前,先看用户是否已经回答 | | |
| `dispatch` | 有依据的问题由主控回答,需要新判断的转给用户 | | |
| `dispatch` | 在主控处卡住的事交还给用户 | | |
| `dispatch` | 完成与否通过把工作者附上的原始证据与完成标准对照来判断,`gh pr diff` 只在用户问起时才看 | | |
| `dispatch` | 仓库里没有证明手段时只报告,不去制作手段 | | |
| `dispatch` | PR 合并后归档工作者会话 | | |

## 添加技能的标准

- 只放入多个仓库以同样正文使用的技能。只在一个仓库中使用的技能放在那个仓库里。
- 只在真实会话中出现失败时才添加或修改。
- 写过程。能用检查阻止的规则交给仓库的检查。
- 不写与仓库绑定的值。
- 删掉描述模型本来就会做的事的行。
- 正文只按 Claude Code 来写。不考虑其他 AI。

## 参考

- [mattpocock/skills](https://github.com/mattpocock/skills):`grill` 源自 `grilling`,`debug` 源自 `diagnosing-bugs`。
- [cursor/plugins](https://github.com/cursor/plugins) 中的 `pstack`:不附带检查、只面向一种工具来写的做法。
- [poteto/verification-skill-example](https://github.com/poteto/verification-skill-example):验证技能的范例。
