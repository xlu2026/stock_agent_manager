# 仓库约定（给所有在本仓库工作的 Agent）

## 开工先读

动手之前先读 `docs/handoff.md`（当前状态、待办、已踩过的坑）和 `docs/architecture.md`。
不要凭对话印象猜项目进度——对话会丢，文档不会。

这是一个**个人认知记录**项目，不是选股服务。下面几条是一票否决的边界，优先级高于任何技术目标。

## 绝对不做

**A. 对外表达（所有 agent，写作 Agent 尤其严格）**

- 不荐股、不展示个股代码、不给买入/卖出信号、不承诺收益。
- 不调用 `freepublish`，不用浏览器自动化绕过发布限制；发布永远由人手动点。

公众号文章、公开输出、对外回复都属于"对外表达"，上面两条一个字都不放松。

**B. 实盘与下单（只有 Agent 1 走这条路）**

- Agent 1 的路线是：回测 → 模拟盘 → **本人账户实盘 + 自动化执行**，并交付可执行的持仓与订单输出。
  因此"不展示个股代码 / 不给买卖信号 / 不接实盘 / 不下单"这四条**只约束对外表达与其他 agent，不约束 Agent 1 的内部执行**。
- 但 Agent 1 的实盘能力必须同时满足：

  1. **仅限本人账户**，不代客、不托管他人资金、不对外提供交易信号；
  2. **下单能力只存在于量化侧 profile**，不得暴露给写作 Agent 或其他 agent（工具面隔离）；
  3. **凭据与工作区独立**：券商凭据不进仓库、不进对话、不进写作工作区；
  4. **有审计**：每一笔下单都要落盘（时间、标的、方向、数量、价格、来源实验 ID、人工确认标记）；
  5. **先模拟后实盘**：`run_paper_session` 通过后才能接真实通道。

- 当前状态：**Phase 1 未实现任何下单能力**，`live_submit_order` 不存在。上面的 B 是路线授权，不是已有能力——
  在真正实现之前，Agent 1 不得假设、模拟或建议调用下单接口。

**C. 通用**

- 不让 LLM 生成或修改回测净值、指标；这些只能来自 `quant/engine.py`。

上面三组是**行为边界，不是话术**。它们约束"不要做"，不要求"每次回答都声明一遍"。
不需要在无关的回答末尾重复这些限制；只在用户直接问及、或某次操作真的可能越界时提及一次。
边界靠文档承载（`docs/wechat-account.md`、`docs/architecture.md`），不靠复读。

## 目录职责

- `quant/` 量化内核（确定性引擎 + MCP 服务端）。写作侧不得 import。
- `writing/` 写作侧（渲染 + 合规 + 草稿客户端）。**不得 import `quant`**。
- `agents/` 编排层：Agent 1 只用 MCP 工具；Agent 3 没有任何量化工具。
- `cordis/prompts/` 两个 Agent 的系统提示词，是唯一来源；改完跑 `tools/build_cordis.py`。
- `experiments/`、`output/` 运行时产物。

## 写作路径

- **新文章由 Agent 3 成文**：`dsh --profile writing`，工作区 `C:\AI_workspace\wechat_writing`，
  素材包放 `briefs\`，产出落 `articles\`。
- `python -m agents.agent3` 是确定性渲染器，**不是写作 agent**：只用于重渲染已有简报、
  格式修订与合规检查。
- 主会话可以给素材、改稿、复核、推草稿箱，但不代替 Agent 3 成文。
- 文风规则（不用「不是……而是」、不给自己加戏）在 `cordis/prompts/agent3.md`；
  改完提示词要跑 `tools/build_cordis.py` + `tools/install_dsh_profile.py`。
- **全部成文稿都在 `C:\AI_workspace\wechat_writing\articles\`**：`writing/article.py::ARTICLE_DIR`
  默认指向那里，可用 `WFR_ARTICLES_DIR` 覆盖。仓库 `output/articles/` 只放封面素材与导出物，
  验收的渲染副本落 `output/reports/acceptance_article/`。
- 推送与记账走仓库脚本：`push_draft.py --category`（封面按栏目取）、`mark_published.py`（发布回写）、
  `commit_articles.py`（提交工作区）。`output/reports/drafts.jsonl` 是草稿位置的权威账本。
- 每篇成文在 front matter 记 `brief_ref`，指向它对应的简报；没有简报的（口述稿）如实留空。
- 存量例外：2026-11-09 之前成文的 002、003、AI技术 002 由主会话写成，不追溯。

## 修改后必须跑

```powershell
python -m unittest discover -s tests -t .
python scripts\acceptance.py
```

任何一项失败都不算完成。

## 风格

- 只用 Python 标准库：本机无外网 PyPI，加依赖会直接跑不起来。
- 涉及数字的地方保留引擎精度，不要"四舍五入得好看一点"。
- 不确定就写进文档，不要用措辞掩盖。
