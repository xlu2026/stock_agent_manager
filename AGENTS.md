# 仓库约定（给所有在本仓库工作的 Agent）

## 开工先读

动手之前先读：

- `docs/handoff.md`（当前状态、待办、已踩过的坑）
- `docs/architecture.md`
- `docs/metrics-and-benchmarks.md`（基准/Sharpe/成本口径）
- `docs/research-playbook.md`（预注册、训练/测试、walk-forward）
- `docs/review-2026-11-28.md`（最近三个优化点的缺口）

不要凭对话印象猜项目进度——对话会丢，文档不会。

这是一个**个人认知记录**项目，不是选股服务。下面几条是一票否决的边界，优先级高于任何技术目标。

## 绝对不做

**A. 对外表达（所有 agent，写作 Agent 尤其严格）**

- 不荐股、不展示个股代码、不给买入/卖出信号、不承诺收益。
  **复盘类文章可以给市场／资产类别的大方向判断**，但不得落到具体标的与买卖点，且必须写清依据与反证条件。
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
- `agents/` 编排层：Agent 1 只用 MCP 工具；Agent 2 只管数据刷新；Agent 3 没有任何量化工具。
- `cordis/prompts/` 三个 Agent 的系统提示词，是唯一来源；改完跑 `tools/build_cordis.py`。
- `experiments/`、`output/` 运行时产物。

## 写作路径

- **新文章由 Agent 3 成文**：`dsh --profile writing`，工作区 `C:\AI_workspace\wechat_writing`，
  素材包放 `briefs\`，产出落 `articles\`。
- `python -m agents.agent3` 是确定性渲染器，**不是写作 agent**：只用于重渲染已有简报、
  格式修订与合规检查。
- 主会话可以给素材、改稿、复核、推草稿箱，但不代替 Agent 3 成文。
- 文风与写作规范（研究记录体、术语、比喻上限、连续性）在 `cordis/prompts/agent3.md`；专辑上下文卡在 `C:\AI_workspace\wechat_writing\ALBUM.md`；每篇配套 `reports/<slug>.meta.md`（不进公众号）。
  改完提示词要跑 `tools/build_cordis.py` + `tools/install_dsh_profile.py`。
- **全部成文稿都在 `C:\AI_workspace\wechat_writing\articles\`**：`writing/article.py::ARTICLE_DIR`
  默认指向那里，可用 `WFR_ARTICLES_DIR` 覆盖。仓库 `output/articles/` 只放封面素材与导出物，
  验收的渲染副本落 `output/reports/acceptance_article/`。
- 推送与记账走仓库脚本：`push_draft.py --category`（封面按栏目取）、`mark_published.py`（发布回写）、
  `commit_articles.py`（提交工作区）。`output/reports/drafts.jsonl` 是草稿位置的权威账本。
- 每篇成文在 front matter 记 `brief_ref`，指向它对应的简报；没有简报的（口述稿）如实留空。
- 文件名统一 `[栏目_编号] <date>-<slug>.md`：Agent 3 落盘后跑 `scripts\rename_articles.py`（幂等）。
- 存量例外：2026-11-09 之前成文的 002、003、AI技术 002 由主会话写成，不追溯。

## 量化链路统一入口

- **所有登记实验（产出 `experiment_id` 的回测）必须走 Agent 1**：`agents/agent1.py`
  或 `scripts/run_agent1.py`，以及 `dsh --profile quant`。不要用 `quant.engine.run_backtest`
  直接登记实验——否则校验（预热、区间、数据版本）、实验记录、数据指纹会和 Agent 1 不同步。
- 真实数据用 `--data-dir` 指向快照，`universe` 写 `沪深300`（映射到 `hs300_40_pit`）；
  示例见 `examples/research_instruction_hs300.json`。Agent 2 刷新成功后会把最新快照写到
  `output/data/latest.json`，Agent 1 可以直接用 `--latest`。用 `dsh --profile quant` 时，
  先在同一环境里设 `NFR_DATA_DIR` 指向快照（MCP 服务端会继承）。
- 诊断/对照（不登记实验，如 `scripts/compare_datasets.py`）可以直接调引擎，
  但不能绕过 Agent 1 的校验去下"策略有效"的结论。

## 数据刷新路径（Agent 2）

- **取数不是 Agent 1 的事。** 新数据由 Agent 2（`dsh --profile agent2`）刷新：它只挂
  `quant.data_mcp` 的六个工具（`list_snapshots / refresh_snapshot / refresh_status /
  cancel_job / cleanup_jobs / check_snapshot`），没有回测、没有下单、没有 shell。
- 刷新是后台作业：`refresh_snapshot` 返回 `job_id`，必须用 `refresh_status` 轮询到 `succeeded/failed`。
- 环境变量：`NFR_SNAPSHOT_ROOT`、`NFR_BAOSTOCK_PYTHON`（必需）、`NFR_EXPORT_SCRIPT`、
  `NFR_DATA_JOB_DIR`；也可以写在 `config/agent2.json`（已 gitignore，示例见
  `config/agent2.example.json`），环境变量优先。
- 铁律：**不覆盖已有快照**（每次新目录、全 ASCII 路径）；刷新成功后 Agent 2 会更新
  `output/data/latest.json` 指针，Agent 1 用 `--latest` 接上（也可以继续显式传 `--data-dir`）。
- 增量刷新必须继承 base 的 `universe` 名；2026-11-28 修过一次增量丢 `hs300_40_pit` 的问题。
- 刷新后先跑 `scripts/check_snapshot.py <dir>`；改过 manifest/文件内容再跑
  `scripts/rehash_snapshot.py <dir>`。`dv` 是全文件 hash，不再只 hash prices。
- 没有 Agent 2 会话时，人工入口是 `scripts\refresh_and_run.ps1` 或导出脚本，规则相同。

## 研究口径（2026-11-28 起）

- **主基准只有一个**：40 只 PIT 等权、每日再平衡、零成本；QMT 的 000300 只做展示，
  不进入研究结论的“超额/alpha”。
- 登记实验必须走 Agent 1；训练集选参、测试集只跑一次；固定候选不参与每折选参。
- 新策略/新参数/新数据源先填 `templates/pre_registration.md`，结果记入
  `docs/experiment-ledger.md`；不接受“看完测试再改规则”。
- 成本必须注明档位（默认 10bp）；10bp 的正超额不能直接推到 30/50bp。
- 诊断/对照可以直接调引擎，但**不能绕过 Agent 1 的校验去下“策略有效”的结论**。

## QMT / paper（2026-11-28 状态）

- QMT 部署是**确定性生成 + 人工导入**：`quant/deploy/qmt.py`、`scripts/deploy_qmt.py`；
  不自动注册、不自动启动、不自动登录，Agent 4 未建。
- 历史回测版冻结在 `output/qmt/nfr_mom_lowvol.py`（sha `089dfd...`），是执行近似：
  QMT 同 bar 卖出回款不可用，存在现金拖累/整手差，跟踪误差约 4–6%。
- 前向 paper 版在 `output/qmt/nfr_mom_lowvol_paper.py`（sha `9766768f...`）：
  动态月度、追加 NAV、state 防重复调仓；必须在 QMT 模拟账户人工启动。
- 不做实盘、不自动下单、不做两阶段调仓（除非同步改引擎）；详见
  `docs/qmt-alignment-decision.md`、`docs/paper-tracking.md`、`docs/execution-runbook.md`。

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
