# 交接文档（Handoff）

> 给下一个会话的 agent 看的第一份文件。读完这一页，你应该知道：项目在哪一步、
> 什么不能碰、下一步做什么、以及哪些坑别人已经踩过。
>
> 最后更新：2026-11-14 ｜ 对应状态：Phase 1 完成；数据接入走 baostock/CSV 快照，
> 执行侧实测为 SmartX CSV 半自动（见第 7 节与 `docs/smartx-execution.md`）

---

## 1. 三十秒版本

这是一个个人项目：**用 AI 把投资判断写成可回测因子，并公开记录过程**。
Phase 1 已经跑通"研究指令 → 确定性回测 → 指标与实验 ID"，以及公众号文章草稿链路；
Agent 2 数据刷新、Agent 3 写作、发布台也已落地。
**下一步是执行适配与组合构建**：真实 baostock 快照已经跑通（`dv-946b080b1258`），
执行侧停在 SmartX CSV 半自动——能生成 CSV、能自动导出对账，下单确认仍需人工点。
细节见 `docs/smartx-execution.md`。

当前规模：**215 项单测、14 项验收、MCP 14 个工具（research 模式 10 个）+ 6 个 data 工具**，全绿。

---

## 2. 先读什么

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `AGENTS.md` | 行为边界（一票否决项），每个会话自动注入 |
| 2 | 本文件 | 当前状态与待办 |
| 3 | `docs/architecture.md` | 分层、工具面、券商层、数据接入（第 9 节） |
| 4 | `docs/strategy.md` | 策略规格、参数口径、加因子 checklist |
| 5 | `docs/smartx-execution.md` | 执行侧实测：CSV 下单/撤单、字段对照、未决问题 |
| 6 | `README.md` | 快速开始 |
| 7 | `docs/agent-prompt-guide.md` | 给三个 Agent 写提示词的模板与反例 |

公众号账号状态（接口权限、白名单、变现）在 `docs/wechat-account.md`，与本仓库开发解耦。
公众号之外的平台矩阵、知乎导出与发布记录在 `docs/platforms.md`；日常发布流程见 `docs/publishing.md`。

---

## 3. 已完成

| 模块 | 位置 | 状态 |
|---|---|---|
| 确定回测引擎（4 因子、成本、基准、指标、IC） | `quant/engine.py` `quant/factors.py` | ✅ 可复现（`nav_hash`） |
| 四字段研究指令契约（自然语言 → 因子） | `quant/instruction.py` | ✅ 模型不能自选因子 |
| MCP 服务端 | `quant/mcp_server.py` | ✅ 14 个工具；Agent 1 profile 用 `--toolset research`（10 个） |
| 实验登记簿 | `quant/experiments.py` `experiments/` | ✅ 公开记录持仓已脱敏；代码在 `experiments/.private/` |
| 模拟盘 + 券商抽象层 | `quant/paper.py` `quant/broker/` | ✅ 只有 PaperBroker |
| 下单三段式（提案 → 人工批准 → 提交） | `quant/broker/proposals.py` `approve.py` | ✅ 已实测 |
| 写作侧（渲染、合规、草稿接口） | `writing/` | ✅ |
| 知乎导出（HTML/MD/meta，无发布） | `writing/platforms/zhihu.py` `writing/export.py` | ✅ 导出 + 人工清单；文末自动加首发句 |
| 知乎发布（开篇） | https://zhuanlan.zhihu.com/p/2103182137985976284 | ✅ 2026-11-09 手动发布；AI 声明/首发句/3 话题已核对 |
| 发布台（状态/卡片/回填） | `writing/publishing.py` `scripts/publish.py` | ✅ 只读聚合 + prepare 卡片 + done 回填，无发布 |
| DSH 三套 profile（工具面隔离） | `cordis/` + `tools/build_cordis.py` | ✅ quant / writing / agent2 |
| 数据契约 v2 + 快照体检 + 通用 CSV 导入器 | `quant/providers/` | ✅ 消费端已认 v2，无真实数据 |
| 真实数据导出（baostock，含时点成分）+ 数据对照 | `scripts/export_baostock_snapshot.py` `scripts/compare_datasets.py` | ✅ 40 只×2019-2024，`dv-632cc7c31340` |
| Agent 2 数据运维（后台刷新作业 + 体检） | `quant/data_mcp.py` `quant/data_jobs.py` `cordis/profiles/agent2.yml` | ✅ 6 个工具，不跑回测 |
| QMT 只读导出 sidecar（不下载） | `scripts/export_qmt_snapshot.py` | ⚠️ 个人 QMT 已停，脚本保留备查 |
| SmartX CSV 执行链路（下单/撤单实测） | `docs/smartx-execution.md` | ✅ 半自动；确认框人工，导出自动 |
| SmartX 自动导出对账 | `quant/broker/smartx_export.py` `scripts/reconcile_smartx.py` | ✅ 6 个 CSV 解析 + rowId 对账 + 归档 |
| SmartX 下单 CSV 生成 | `quant/broker/smartx_csv.py` `scripts/make_smartx_csv.py` `scripts/fetch_quotes.py` | ✅ 不复权报价 + 提案→CSV；不提交 |
| 策略规格文档 | `docs/strategy.md` | ✅ v1.0 |

---

## 4. 未完成 / 下一步

**统一入口（2026-11-11 定）**：所有**登记实验**必须走 Agent 1——`scripts/run_agent1.py` 或
`dsh --profile quant`。真实数据用 `--data-dir` 指向快照（universe 写 `沪深300`，映射到
`hs300_40_pit`）。直接调 `quant.engine.run_backtest` 只用于诊断/对照，**不登记实验**，
也不跳过 `validate_strategy` 的预热与区间校验。

**取数走 Agent 2（2026-11-11 新增）**：`dsh --profile agent2`，只挂 `quant.data_mcp` 的
`list_snapshots / refresh_snapshot / refresh_status / check_snapshot`。刷新是后台作业，
轮询到 `succeeded` 后再把新目录交给 Agent 1。没有 Agent 2 会话时用
`scripts\refresh_and_run.ps1`（规则相同）。

按优先级：

| # | 任务 | 阻塞点 |
|---|---|---|
| 1 | 等中泰答复：下单确认框能否免确认、生产账号类型是否与测试一致、收盘导出文件命名 | 决定执行层停在半自动还是能往前走 |
| 2 | 把 `SmartXCsvBroker` 接成 `Broker` 适配器：生成 CSV + 读导出对账；提交永远人工 | CSV 生成与对账已完成，缺统一接口适配 |
| 3 | 真实快照已导入；补双源交叉校验、财报重述检测 | baostock 是单源，静默取错难发现 |
| 4 | 组合构建层（多因子、权重、敞口上限） | 未开始 |
| 5 | 公众号：原创声明 + 赞赏 | 需用户在后台手动勾（OpenAPI 无此字段） |

**两条线可以并行**：数据侧继续补质量校验（第 3 步），执行侧在第 1 步答复前只做
“提案 → CSV”的离线部分，不碰提交。

---

## 5. 不能碰的边界

完整版在 `AGENTS.md`，这里只列最容易搞错的：

- **两个平面**：对内执行（Agent 1 可以出现标的、方向、订单）≠ 对外表达（文章、公开输出一律不许出现个股代码/买卖信号/收益承诺）。
- **模型不能选因子**：`factor_logic` 由 `quant/instruction.py` 的关键词表映射，不要给模型加 `factor` 参数。
- **净值只能由引擎算**：任何"模型估算收益"都是红线。
- **下单必须人工批准**：`approve` CLI 是唯一入口，量化 profile 没有 shell，Agent 跑不了这一步。**不要把 approve 包成 MCP 工具**。
- **不要把发布能力**加进任何 agent。

---

## 6. 环境与坑（都已踩过）

| 现象 | 原因 | 处理 |
|---|---|---|
| `import quant.data` 报空包 | `quant/data/` 与 `quant/data.py` 同名共存 | **绝不能**在 `quant/data/` 放 `__init__.py` |
| 中文输出乱码 | Windows 控制台 GBK | 脚本里先 `force_utf8()`（`quant/console.py`） |
| PS 写文件带 BOM，JSON 解析失败 | PowerShell 5.1 `Set-Content -Encoding utf8` 带 BOM | 用 `[IO.File]::WriteAllText` + `UTF8Encoding($false)`；读用 `utf-8-sig` |
| **改文档整篇变乱码** | `Get-Content` 读无 BOM 的 UTF-8 会按系统 ANSI(cp936) 解码，再 `Set-Content` 就把乱码写回去，且**不可逆**（本次 README/handoff 各中过一次，从会话记录里重建） | 改 md 用编辑器或 agent 的编辑工具，别用 PowerShell 的 `Get-Content`/`Set-Content` 管道；必须用 PowerShell 时显式 `-Encoding utf8` 读写 |
| `.ps1` 中文全乱、语法报错 | 无 BOM 的 UTF-8 被当 ANSI | 脚本存成 UTF-8 **带 BOM** |
| `pytest`/`pip install` 不可用 | 本机无外网 PyPI，只有 DeepSeek API 可达 | 全链路只用标准库 |
| `dsh` 命令找不到 | 不在 PATH | 用全路径 `...\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd` |
| 盘中刷新后快照整份加载失败 | 交易日历已含“今天”，但当天行情未生成，`calendar.csv` 末尾一天无报价 | 导出器已把日历/成分裁到最后一个有行情的日期（`calendar_trimmed` 写进 notes）；旧快照需重刷 |
| 下单被拒“价格超出涨跌停范围” | 用了后复权快照价（601939 快照 30.3099，名义收盘 11.92） | 下单前跑 `scripts/fetch_quotes.py` 取不复权价，生成 CSV 必须带 `--quotes` |
| 两个内容不同的快照 `dv` 相同 | `manifest.sha256` 目前只覆盖 `prices.csv`，`calendar/universe` 变化不改变 `dv` | 已知问题；复现时同时核对 `files.*.sha256`，待改成全文件哈希 |
| `dsh headless` 用不了 preset | 源码硬限制（headless 不消费 preset） | 用 profile 级隔离 |
| 微信错误被判成"成功" | HTTP 200 + body 里带 errcode | `probe_draft_api` 已按 errcode 分类，别再改回去 |
| 沙箱里跑测试全红 `PermissionError` | Python 3.12 的 `tempfile.mkdtemp` 在 Windows 建出仅所有者可访问的目录，沙箱令牌进不去；与代码无关 | 用完整权限（full access）跑，或在用户自己的终端里跑；不要为此改测试 |

验证命令（改完必须跑）：

```powershell
python -m unittest discover -s tests -t .
python scripts\acceptance.py
```

---

## 7. 数据源与执行通道（2026-11-11 更新）

**执行侧已有答案，停在半自动**：miniQMT 对个人已全部停用（客服口径），QMT 只剩
客户端内置策略、拿不到外部信号；SmartX Python 组件是沙箱；可用的是客户端
「下单 → CSV → 选择上传」或 CLI `startCSV`——能下单、能撤单；下单确认人工点，
委托/成交/持仓/资产自动导出。
完整实测记录（字段对照、错误码、操作流程、未决问题）见 `docs/smartx-execution.md`。

**数据侧已改道**：QMT 终端里已下载的数据还能读、能导出（2026-11-09 确认），但 QMT 对个人
已停用，不再作为长期数据源。真实数据走 baostock → CSV → v2 快照，见下面的已落地路径。

**已落地的真实数据路径**：`scripts/export_baostock_snapshot.py`（在装了 baostock 的
Python 里跑，例如 SmartX 自带的 `bin\cpython\python.exe`）→ `csv_import` 生成快照。
默认走**时点成分**：每月末查一次 HS300 名单，按返回的 `updateDate` 前向填充到每个交易日；
`--no-pit-universe` 可退回当前名单。

最新真实快照 `dv-946b080b1258`（2026-11-12 增量刷新）：2019-01-02 ~ 2026-11-11，
40 只时点成分，1905 个交易日，70,931 行价格，体检 9 项全过。
**所有登记实验统一走 Agent 1**；真实数据示例见 `examples/research_instruction_hs300.json`。
本轮实测：Agent 2 增量刷新 → Agent 1 动量回测 `exp-156080bc8d3f`（2021-01-04~2026-11-11，
cagr -0.0646、sharpe -0.2085、回撤 -0.5201、IC -0.0164）。

旧快照 `dv-632cc7c31340`（2019-2024，1456 天）仍保留，历史实验 `exp-3e14b6dd0170` 用它复现。

同参数对照（`2021-01-04~2024-12-31`，报告见 `output/reports/real_vs_synthetic.md`）：

- 等权基准：固定池 7.94% → 时点 **-3.51%**，约 11.5pp 是名单层面的幸存者偏差；
- 动量：合成 +11.34% → 真实 **-7.76%**（IC 0.002、回撤 -52%）——合成数据的"强动量"是假象；
- 低波动：合成 -13.04% → 真实 **+8.26%**（IC 0.141，最强），方向翻转；
- 质量：真实 **-12.91%**（IC -0.059），合成正号不可迁移；
- 价值：真实 +8.37%（IC 0.077），三个版本都为正，但口径仍偏。

窗口从 2020-01-02 改成 2021-01-04 是因为动量需要 252 天预热而 2020 起点只有 244 天——
Agent 1 的 `validate_strategy` 拦住了，直接调引擎的旧对照没有拦。

**刷新方式**：优先走 Agent 2（`dsh --profile agent2`）——它调 `refresh_snapshot` 启后台作业，
用 `refresh_status` 轮询，完成后报告新 `dv`。底层是 `--incremental --base-dir <旧快照>`：默认拿
最近 10 个交易日做重叠比对，收盘价变化超过 1e-4 判定为除权/数据修订，自动回退全量；财报只补
最近 4 个季度（重述靠定期全量）。没有 Agent 2 会话时用 `scripts\refresh_and_run.ps1`
（PowerShell 执行策略需 `Bypass`）。**输出目录不能等于 base**，每次刷新换新目录，旧实验才能按旧
`dv-…` 复现。Agent 2 需要的环境变量：`NFR_SNAPSHOT_ROOT`、`NFR_BAOSTOCK_PYTHON`（必需）、
`NFR_EXPORT_SCRIPT`、`NFR_DATA_JOB_DIR`。

（下面这段是 QMT 只读导出的历史记录，个人已无法使用，保留备查。）

```powershell
# 先探本地有什么，不写文件
python scripts\export_qmt_snapshot.py --probe --stocks 600000.SH,000001.SZ --start 20190101 --end 20241231
# 正式导出（可选时点成分 / 财报 CSV）
python scripts\export_qmt_snapshot.py --stocks ... --start ... --end ... --out snapshots\qmt --universe csi300
```

注意：脚本要在**能 import `xtquant` 的那个 Python** 里跑。如果券商只允许在客户端进程内
运行，就退回"终端内手工导出 CSV → `python -m quant.providers.csv_import`"。

**备选数据源**（上面这条路走不通时，按与本仓库约束的匹配度）：

1. **通达信本地日线**（`.day` 定长记录 + `gbbq` 除权数据）：完全离线、纯标准库、无需 pip。
   缺点：格式无官方文档、复权要自己算、退市与停牌要自己处理。
2. **baostock / akshare / Tushare**：装在你自己的机器上，导出 CSV 交给仓库。
   baostock 免费、自带复权因子与交易日历，最省事。
3. **公开 HTTP 接口**（东财/新浪/腾讯）：纯标准库可做，但非官方、会变、有限流，
   适合做**交叉校验**，不适合当唯一来源。
4. **付费源**（Tushare Pro 积分、Wind、聚宽）：花钱买确定性，建议二期。

**不变的红线**：不绕过 QMT 的文件/网络限制（改配置、注入、代理）。那是券商协议与监管问题。

**结论**：本地快照 + sha256 复现的架构不依赖券商，数据侧只需要一份可复现的 CSV。
执行侧不再追求"外部 API"，接受 SmartX CSV 的半自动流程（人工确认 + 自动导出 + 仓库对账）；
能不能再往前走（免确认、自动导出）取决于中泰答复，见 `docs/smartx-execution.md` 第 5 节。

---

## 8. 关键 ID（运维用，勿丢）

| 项 | 值 |
|---|---|
| 基准实验（动量，top_k=8） | `exp-a359c2d77697` |
| 基准 `nav_hash` | `fc5c9e778707e5f1280d1084c4018342aa4013a248e9aec2b3b2391b64a47f1a` |
| 数据快照版本 | `dv-572bafec2a92`（40 标的 × 1565 交易日，sha256 固定） |
| 真实快照（baostock，时点成分，最新） | `dv-946b080b1258`（40 标的 × 1905 交易日，2019-2026-11-11） |
| 真实数据 Agent 1 实验（最新） | `exp-156080bc8d3f`（2021-01-04~2026-11-11，动量） |
| 真实快照（baostock，时点成分，历史） | `dv-632cc7c31340`（40 标的 × 1456 交易日，2019-2024） |
| 真实数据 Agent 1 实验（历史） | `exp-3e14b6dd0170`（2021-01-04~2024-12-31） |
| 真实快照（固定池，历史对照） | `dv-2ccb7042aaf5`（35 标的，有幸存者偏差，勿用于结论） |
| 引擎版本 | `engine-0.1.0` |

`dv-572bafec2a92` + 上面那个 `nav_hash` 是回归锚：2026-11-09 改 `load_panel` 认 v2 之后
两者都逐位未变（`tests/test_data_v2.py::test_v1_sample_is_unchanged` 守着）。
以后动数据加载，先看这两个值有没有漂。

---

## 9. 给下一个 agent 的开场建议

先跑这三条确认环境没坏：

```powershell
python -m quant.cli doctor
python -m unittest discover -s tests -t .
python scripts\acceptance.py
```

然后读 `docs/architecture.md` 第 9 节与 `docs/smartx-execution.md`。真实快照和 Agent 2 刷新
已经落地，下一步不是“找数据”，而是执行适配与组合构建：

1. SmartX CSV → `Broker` 适配（生成与对账已完成，缺统一接口）；
2. 双源交叉校验 / 财报重述检测；
3. 组合构建层（多因子、权重、敞口上限）。

先跑这三条确认最新快照可用：

```powershell
python -m quant.cli doctor
python scripts\run_agent1.py --instruction examples\research_instruction_hs300.json --latest
python scripts\publish.py status
```

不要重新设计架构——现有分层是有理由的，改动前先看第 5 节。

---

## 10. 写作路径（2026-11-09 定）

**新文章必须由 Agent 3 成文**，不是由主会话直接写。

```powershell
cd C:\AI_workspace\wechat_writing
& "<DSH>\runtime\cli\bin\dsh.cmd" --profile writing "读取 briefs\xxx.json，按系统提示词写一篇草稿保存到 articles\"
```

- 素材包放 `C:\AI_workspace\wechat_writing\briefs\`，字段按 `cordis/prompts/agent3.md` 第一节
  （`experiment_id / data_source / research_question / factor_logic / backtest_summary / user_notes / target_structure / timestamp`）。
  `user_notes` 是观点来源，最关键。
- 产出落 `C:\AI_workspace\wechat_writing\articles\`；推草稿箱仍回仓库用 `scripts\push_draft.py`。
- `python -m agents.agent3` 只是**确定性渲染器**，用于重渲染已有简报、格式修订、合规检查，
  不承担成文。它不调用模型，跑过它不代表 Agent 3 写了文章。
- 文风规则（不用「不是……而是」、不给自己加戏）在 `agent3.md` 的三.9/三.10 与六.9/六.10，
  只对 writing profile 生效；主会话直接写稿时不受它约束。
- **存量例外**：002、003、AI技术 002 是 11-09 之前主会话写的，不追溯。
- **文章只在一个地方**：`C:\AI_workspace\wechat_writing\articles\`（独立 git 仓库）。
  `ARTICLE_DIR` 默认指向那里；仓库 `output/articles/` 只剩封面与导出物，
  验收渲染副本在 `output/reports/acceptance_article/`。
- **推送与记账的入口**（都在仓库侧，写作会话没有 shell）：
  - `scripts\push_draft.py --file <文章> --category <栏目>`：封面按 `covers/manifest.json` 取，
    成功后追加 `output/reports/drafts.jsonl` 与 `output/reports/compliance-<slug>.json`；
  - `scripts\mark_published.py <slug>`：发布后改 front matter、追加工作区 CHANGELOG、git 提交；
  - `scripts\commit_articles.py -m "..."`：单独提交工作区。
- `drafts.jsonl` 是"这篇在哪个草稿"的权威账本，`docs/wechat-account.md` 的资产表只是摘要。
