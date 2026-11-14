# 架构与合规说明（当前：三 Agent + 数据 / 执行 / 发布链路）

这份文档描述**当前代码实际怎么分层**，以及哪些能力在架构上不可达。
任务书条目与实现的对应关系放在第 6 节；历史冲突与替代方案放在第 5 节。

---

## 1. 当前事实与不确定点

### 1.1 已验证（有命令、有证据）

| 项 | 结论 | 验证方式 |
|---|---|---|
| Python | 3.12.8，纯标准库可跑主链路 | `python --version`、`tests/` |
| DSH | Desktop 版，`dsh` CLI 可用；三个 profile 可安装 | `dsh --profile ...`、`~/.dsh/profiles/` |
| Cordis | 自定义 profile 可组合，`--dump-config` 成功 | `output/evidence/composed_config_*.txt` |
| MCP stdio | DSH 能 spawn 并连接本地 MCP 服务端 | `[srq-compat] ready on stdio`、`scripts/verify_mcp.py` |
| Agent 1 工具面 | `srq` full 14 个；research 模式 10 个 | `quant/mcp_server.py`、`cordis/profiles/quant.yml` |
| Agent 2 工具面 | `data`（内部名 `data-ops`）6 个（列快照 / 刷新 / 状态 / 取消 / 清理 / 体检） | `quant/data_mcp.py`、`cordis/profiles/agent2.yml` |
| Agent 3 工具面 | `draft` 3 个草稿/合规工具，无发布 | `writing/draft_mcp.py` |
| 数据 | 合成锚 `dv-572bafec2a92`；真实 baostock 快照 `dv-946b080b1258`（40 只 × 1905 天，2019-01-02~2026-11-11） | `quant/cli.py doctor`、`docs/handoff.md` |
| 执行 | SmartX CSV 半自动：生成 CSV → 人工上传/确认 → 自动导出对账 | `docs/smartx-execution.md` |
| 发布 | 微信只到草稿；知乎只到本地导出；发布永远人工 | `docs/platforms.md`、`docs/publishing.md` |
| 回归 | 215 项单测、14 项验收 | `python -m unittest ...`、`scripts/acceptance.py` |

### 1.2 与原始任务书假设不一致（已确认）

| 任务书假设 | 实际 | 影响 |
|---|---|---|
| `deepseek-harness-sdk` 已安装 | PyPI 无此包，本机也没有 | 控制平面用 `dsh` CLI + `agents/mcp_client.py` |
| `solidrock-quant[mcp,sources]` 已安装 | 本机没有 `srq`，也装不了 | 自建 `srq-compat`，工具名对齐，引擎纯 stdlib |
| PyPI 可用来装依赖 | 不可达 | 仓库主链路只用标准库；baostock/xtquant 只在外层脚本里 import |
| 数据源随手可得 | QMT 对个人已停用；真实日线走 baostock 导出 + CSV 快照 | 数据与券商解耦，快照可复现 |
| 交易通道走 QMT/miniQMT | 个人已停用；SmartX Python 组件是沙箱 | 执行停在 SmartX CSV 半自动，人工确认 |
| 公众号/知乎可程序化发布 | 公众号只有草稿接口；知乎没有公开写接口 | 只做草稿与导出，发布人工 |

### 1.3 仍然不确定

- **真实 SolidRockQuant 的返回字段**：`srq-compat` 的字段名是按项目契约自定的，接真机要逐项映射。
- **baostock 的数据质量**：免费公开源，有延迟、可能重述；财报重述不会被增量发现。
- **SmartX 能否免确认 / 生产账号类型**：取决于券商答复；当前确认框必须人工点。
- **公众号 `draft/add` 的长期权限、IP 白名单稳定性**：配置问题，不是代码问题。
- **知乎编辑器对 HTML 的解析**：已用开篇实测过段落/分割线，行内代码与斜体仍需人工微调。

---

## 2. 分层：三个 Agent + 一条发布台

```
                    ┌─────────────────────────────┐
                    │ Agent 2（profile: agent2）   │
                    │ data-ops：刷新/体检快照      │
                    └──────────────┬──────────────┘
                                   │ 写 snapshots + output/data/latest.json
                                   ▼
┌──────────────────┐    ┌─────────────────────────────┐
│ 研究指令（四字段）│───▶│ Agent 1（profile: quant）    │
└──────────────────┘    │ srq：research 10 / full 14   │
                        │ 只编排，不计算               │
                        └──────────────┬──────────────┘
                                       │ 实验记录 / 指标 / 实验 ID
                                       ▼
                        ┌─────────────────────────────┐
                        │ Agent 3（profile: writing）  │
                        │ draft：3 个草稿/合规工具     │
                        │ 无量化工具、无发布能力        │
                        └──────────────┬──────────────┘
                                       │ 文章 + 平台版本
                                       ▼
                        ┌─────────────────────────────┐
                        │ 发布台（scripts/publish.py） │
                        │ status / prepare / done      │
                        │ 只读写本地文件，不发布        │
                        └──────────────┬──────────────┘
                                       │ 微信草稿 / 知乎导出
                                       ▼
                                  人手动发布
```

- **Agent 1（量化）**：只做编排。四字段指令由 `quant/instruction.py` 映射成 spec，
  引擎在 `quant/engine.py` 算净值和指标，实验登记到 `experiments/`。
- **Agent 2（数据运维）**：只刷新和体检数据。刷新是后台作业，`refresh_snapshot` 立刻返回
  `job_id`，由 `refresh_status` 轮询；成功后更新 `output/data/latest.json` 指针。
- **Agent 3（写作）**：把简报写成文章，最高到公众号草稿或本地 Markdown；没有发布能力。
- **发布台**：不是 Agent，是确定性脚本。把 Agent 3 的产物导出成平台版本、生成清单、回填 URL。
  它没有浏览器、没有发布接口。

### 2.1 控制平面与工作区

| 入口 | 作用 |
|---|---|
| `scripts/run_agent1.py` | Agent 1 的 Python 入口：四字段指令 → 信封 |
| `scripts/refresh_and_run.ps1` | 没有 Agent 2 会话时的人工刷新入口（规则相同） |
| `scripts/export_baostock_snapshot.py` | 在带 baostock 的 Python 里导出 v2 快照 |
| `scripts/publish.py` | 发布台：状态 / 卡片 / 回填 |
| `scripts/acceptance.py` | 验收 |
| `agents/mcp_client.py` | MCP stdio 协议客户端 |
| `agents/envelope.py` | 统一输出信封（Router 的消费契约） |

工作区：

- Agent 1、Agent 2：仓库根（要读 `experiments/`、`output/data/`）。
- Agent 3：`C:\AI_workspace\wechat_writing`（独立 git 仓库）。
- 发布台：仓库根（读文章导出与 sidecar）。

### 2.2 目录树（当前）

```
stock_agent_manager/
├─ quant/                       # 量化域（写作侧禁止 import）
│  ├─ instruction.py            # 四字段契约 -> spec（关键词表）
│  ├─ spec.py / validate.py     # spec 与回测前校验
│  ├─ data.py                   # 快照加载 + sha256 校验
│  ├─ data_pointer.py           # output/data/latest.json 指针
│  ├─ data_jobs.py              # 刷新作业目录/状态
│  ├─ data_mcp.py               # Agent 2 的 data-ops MCP 服务端（6 个工具）
│  ├─ factors.py / engine.py    # 4 因子 + 确定性回测
│  ├─ experiments.py            # 实验登记簿（公开记录脱敏）
│  ├─ paper.py                  # 模拟盘
│  ├─ mcp_server.py             # srq-compat：full 14 / research 10
│  ├─ cli.py / console.py       # srq CLI / UTF-8 输出
│  ├─ data/                     # 合成样本（prices.csv + manifest.json）
│  ├─ providers/                # CSV 导入 / QMT 只读 / 体检 / 契约
│  │  ├─ csv_import.py
│  │  ├─ qmt.py
│  │  ├─ contract.py
│  │  └─ snapshot_check.py
│  └─ broker/                   # PaperBroker + 提案/批准 + SmartX CSV 工具
│     ├─ paper.py / proposals.py / approve.py / ledger.py
│     ├─ smartx_csv.py          # 提案 -> SmartX CSV（不提交）
│     └─ smartx_export.py       # 读 6 个导出 CSV 并对账
├─ writing/                     # 写作域（禁止 import quant）
│  ├─ article.py                # front matter 渲染
│  ├─ compliance.py             # 合规闸门
│  ├─ wechat.py                 # 草稿接口客户端（无 freepublish）
│  ├─ drafts.py                 # 写草稿的唯一实现
│  ├─ draft_mcp.py              # 草稿 MCP（3 个工具）
│  ├─ publishing.py             # 发布台：状态聚合/卡片/回填
│  ├─ platforms/zhihu.py        # 知乎导出（无发布）
│  └─ export.py                 # 平台导出 CLI
├─ shared/mcp_stdio.py          # 中立 MCP 协议层
├─ agents/                      # Agent 1/3 的 Python 编排；Agent 2 是 profile+MCP
│  ├─ agent1.py / agent3.py
│  ├─ mcp_client.py
│  └─ envelope.py
├─ cordis/
│  ├─ prompts/agent1.md, agent2.md, agent3.md
│  ├─ profiles/quant.yml, agent2.yml, writing.yml
│  └─ phase1-presets.yml
├─ scripts/                     # Agent 1/2 入口、导出、发布台、验收、SmartX 工具
├─ config/                      # agent2.example.json / publishing.json（无凭据）
├─ tools/                       # 数据生成、Cordis 构建、封面、asar 读取器
├─ examples/                    # 四字段指令、内部 spec、写作简报
├─ docs/                        # 本文件、handoff、strategy、平台/发布文档
├─ tests/                       # 215 项回归测试
├─ bin/srq.cmd                  # srq 兼容入口
├─ experiments/                 # 公开实验记录；.private/ 存个股代码（gitignore）
└─ output/                      # reports / articles / data / evidence / broker
```

---

## 3. 禁止事项的可达性分析

| # | 禁止事项 | 架构上如何不可达 | 验证 |
|---|---|---|---|
| 1 | 不自动发布公众号；不调用 `freepublish`；不浏览器自动化 | 写作 MCP 只注册 3 个草稿工具；仓库无 `freepublish`；发布台只写本地文件；三个 profile 都关闭 web/浏览器相关工具 | `tests/test_writing.py::test_no_publish_surface`、`tests/test_publishing.py::test_no_publish_surface` |
| 2 | 不暴露 `live_submit_order`；无程序化下单适配器 | 全仓无 `live_submit_order`；唯一的 Broker 实现是 `PaperBroker`；`broker_*` 工具全部落 PaperBroker，提交前必须有人工批准文件。SmartX CSV 只是“生成文件 + 人工上传 + 人工确认”，不是 Broker 适配器 | `acceptance.py` 检查 7/9、`verify_mcp.py` 的 `broker_requires_human_approval` |
| 3 | 不向 Agent 3 暴露量化工具 | 写作 profile 不注册 `srq`，只有 `draft`；实测写作会话无 `mcp__srq__*` | `dsh_writing_no_quant_tool.jsonl` |
| 4 | Agent 2 不跑回测、不写实验 | `data-ops` 只注册 6 个数据工具；没有 `run_backtest`、没有 `experiments/` 写入 | `quant/data_mcp.py`、`tests/test_data_mcp.py` |
| 5 | 不让 LLM 生成/修改净值 | 净值只在 `quant/engine.py` 产生；MCP 返回 `nav_hash` 与指标；`get_experiment` 默认不带净值序列 | `test_same_spec_same_nav_hash` |
| 6 | 不把“AI 量化选股”写进名称/简介 | `writing.compliance.check_name` 拦 10 个词；文章合规扫描覆盖 title + tags | `test_name_channel_words` |
| 7 | 不实现 Router / 自主调度 / Agent 4 | 没有 Router；`envelope` 只有 `handoff_eligible` 标记；发布台是脚本，不是 Agent；三个 profile 都关闭 subagent/workflow/schedule | 目录树、`tools/build_cordis.py` |
| 8 | 不自动同步知乎 | 没有知乎写接口调用；只导出 HTML/MD/meta；发布由人手动完成 | `writing/platforms/zhihu.py`、`docs/platforms.md` |

### 3.1 「对内执行」与「对外表达」是两个平面

| | 对内执行（Agent 1） | 数据运维（Agent 2） | 对外表达（Agent 3 / 发布台） |
|---|---|---|---|
| 个股代码 | ✅ 持仓、订单草案 | ❌ 不接触持仓 | ❌ 绝对不出现 |
| 买卖方向 | ✅ 订单 | ❌ | ❌ 不出现 |
| 收益表述 | 引擎指标，可陈述统计事实 | ❌ 不解读收益 | 不承诺收益、不写成“业绩” |
| 下单 | 提案 → 人工批准 → PaperBroker；SmartX CSV 需人工上传确认 | 不涉及 | 不存在 |
| 发布 | 不涉及 | 不涉及 | 只到草稿/导出，发布由人手动点 |

**缺口（不隐瞒）**：

- 写作会话没有 sandbox 目录白名单；`write` 能写工作区内任意文件。这是工作区隔离，不是安全边界。
- 合规扫描是正则 + 句内否定窗口，反讽和长分句可能漏判；所以草稿永远是 `draft`，发布永远人工。
- Agent 2 的刷新依赖外部 baostock 环境；网络/登录失败时只能报告，不保证“一定最新”。

---

## 4. 三个 Agent 的工具面

| | Agent 1（quant） | Agent 2（agent2） | Agent 3（writing） |
|---|---|---|---|
| MCP 服务端 | `srq`：research 10 / full 14 | `data`（profile 名；内部名 `data-ops`）：6 | `draft`：3 |
| 文件工具 | read/write/edit/glob/grep/read_image | 同左 | 同左 |
| shell | **无** | **无** | **无** |
| subagent / workflow / web | **无** | **无** | **无** |
| 量化/回测工具 | 10（research）或 14（full） | **0** | **0** |
| 发布工具 | 无 | 无 | 无 |
| 实测工具总数 | 20 | 6 个 MCP + 文件工具（未单独实测总数） | 12 |

共同关闭的能力由 `tools/build_cordis.py` 的 `DISABLED_TOOLS` 统一生成，避免三个 profile 漂移。

Agent 1 research 模式的 10 个工具：`run_research_instruction`、`run_research_factor_analysis`、
`run_research_paper_session`、`list_experiments`、`get_experiment`、`get_experiment_holdings`、
`broker_account`、`broker_orders`、`broker_propose_order`、`broker_submit_order`。
full 模式额外有 `run_backtest`、`validate_strategy`、`run_factor_analysis`、`run_paper_session`。

Agent 2 的 6 个工具：`list_snapshots`、`refresh_snapshot`、`refresh_status`、`cancel_job`、
`cleanup_jobs`、`check_snapshot`。`refresh_snapshot` 只启后台作业，不阻塞 MCP 调用。

Agent 3 的 3 个工具：`wechat_probe_draft`、`wechat_add_draft`、`article_check_compliance`。

---

## 5. 与 DSH / 外部环境的冲突及替代

### 5.1 Python SDK 不存在

- 控制平面用 `dsh` CLI + `agents/mcp_client.py`，与 SDK 等价地走 MCP。
- 迁移缝：`agents/envelope.py` 与 `agents/mcp_client.py`。

### 5.2 `dsh headless` 不消费 agent preset

- 用 **profile 级隔离**（quant / agent2 / writing 三个 profile）。
- preset 形态保留给 Web 会话；headless 必须起独立进程。

### 5.3 SolidRockQuant 不存在

- `srq-compat` 按项目契约自建，`bin/srq.cmd` 提供 `srq mcp serve`。
- 不是 SolidRockQuant，字段名与语义需要接真机时映射。

### 5.4 `factor_logic` 不能让模型自己选

- 契约解析与因子映射在 `quant/instruction.py` 的关键词表里完成。
- `run_research_instruction` 只接受四字段，模型没有 `factor` 参数；歧义报 `FACTOR_AMBIGUOUS`。

### 5.5 QMT 停用：数据与执行必须解耦

- 数据侧：QMT 只读导出保留为历史备查；真实数据走 baostock → CSV → v2 快照。
- 执行侧：miniQMT 对个人停用；SmartX Python 组件是沙箱；可用的是 SmartX CSV 半自动。
- 结论：引擎只认快照，不认券商；执行只认“提案 → CSV → 人工确认 → 导出对账”，没有程序化下单。

---

## 6. 一致性矩阵（当前实现）

| 条目 | 实现 | 证据 |
|---|---|---|
| 三 Agent 隔离 | 三个 Cordis profile，各自 MCP 与提示词 | `cordis/profiles/*.yml`、工具面实测 |
| 四字段输入契约 | `quant/instruction.py` + `run_research_instruction` | `tests/test_instruction.py` |
| 净值不由 LLM 算 | 引擎唯一计算入口，`nav_hash` 覆盖净值 | `test_same_spec_same_nav_hash` |
| 数据可复现 | 快照 + `manifest.json` sha256 + `dv-…` | `quant/data.py`、`docs/handoff.md` |
| 数据刷新 | Agent 2 `data-ops` 后台作业 + 指针 | `quant/data_mcp.py`、`tests/test_data_mcp.py` |
| 执行人工闸门 | 提案 → 人工批准 → PaperBroker；SmartX CSV 人工确认 | `acceptance.py`、`docs/smartx-execution.md` |
| 发布人工闸门 | 草稿/导出 + 发布台清单；无浏览器/发布接口 | `tests/test_publishing.py` |
| 手动触发、不常驻 | 每次 `dsh` 起进程跑一次 | 工具面实测 |

---

## 7. 券商通道与 SmartX 半自动执行

`quant/broker/` 是**契约**，不是某家券商 SDK 的封装。`PaperBroker` 是唯一 Broker 实现，
按快照收盘价成交，收佣金（万 2.5，最低 5 元）与卖出印花税（千 1），不联网、不读券商凭据。

三道具名闸门：

| 闸门 | 实现 | 行为 |
|---|---|---|
| 人工确认 | `OrderRequest.human_confirmed` | 为假一律拒单（`NOT_CONFIRMED`） |
| 风控上限 | `RiskLimits` | 单笔名义金额、单日单数、单标的持仓上限、现金/持仓充足性 |
| 审计落盘 | `broker/ledger.py` | 每笔（含被拒）追加 JSONL：时间、标的、方向、数量、价格、费用、实验 ID、确认标记 |

三段式：

```
Agent  broker_propose_order ──▶ 提案文件（不产生订单）
人     python -m quant.broker.approve <提案ID>   ← 唯一批准入口，需要 shell
Agent  broker_submit_order  ──▶ 校验批准记录 / sha256 / 有效期 / 是否已提交
```

**SmartX CSV 半自动**（当前实际可用的执行方式）：

1. `scripts/fetch_quotes.py` 取不复权价（避免后复权价触发涨跌停拒单）。
2. `scripts/make_smartx_csv.py` 把已批准提案生成 SmartX CSV（只生成文件，不提交）。
3. 人工在客户端「下单 → CSV → 选择上传」核对并点「下单」；或 `smartx-cli startCSV` 后人工确认。
4. 客户端每 120 秒自动导出 6 个 CSV；`scripts/reconcile_smartx.py` 按 `rowId` 对账。

**尚未实现**：SmartX CSV 到 `Broker` 协议的适配器；任何真实券商适配器。
接入前仍需满足 `AGENTS.md` B 节（仅本人、仅量化 profile、凭据隔离、审计、先模拟后实盘）。
`live_submit_order` 不存在，也不应存在。

---

## 8. 发布链路（Agent 3 + 发布台）

```
brief ─▶ Agent 3 ─▶ articles/*.md（写作工作区）
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
微信 push_draft.py（draft/add）      知乎 writing/export.py（HTML/MD/meta）
        │                                 │
        ▼                                 ▼
   公众号草稿箱                      output/articles/zhihu/
        │                                 │
        └──────────────┬──────────────────┘
                       ▼
             scripts/publish.py
             status / prepare / done
                       │
                  人手动发布
                       │
              done 回填 URL / 日期
```

- 微信：`push_draft.py --category` 只推草稿；原创/AI 声明/合集/赞赏由人在后台勾。
- 知乎：`writing/export.py` 只导出；`writing/platforms/zhihu.py` 自动加首发句；
  没有知乎写接口，发布由人粘贴并点。
- 发布台：`status` 只读聚合，`prepare` 生成发布卡片，`done` 回填；没有浏览器、没有发布接口。
- 账本：`output/reports/drafts.jsonl` 记录草稿 media_id；知乎状态在 sidecar `.zhihu.json`。

---

## 9. 数据接入

现状：**合成样本 + 真实 baostock 快照并存**。默认仍读合成样本；真实数据用
`NFR_DATA_DIR` 或 `--latest` 指向 Agent 2 刷新的快照。

### 9.1 契约先于抓取

`quant/data.py::load_panel()` 是唯一入口，engine / factors / paper / broker 都只认 `Panel`。
所以顺序是：先定“快照长什么样”，再让各家数据源去填。

### 9.2 快照规范（schema v2）

| 文件 | 字段 | 为什么必须有 |
|---|---|---|
| `prices.csv` | date, asset, open, high, low, close, volume, **adj_factor** | 不复权价算收益，除权日就是假跌停 |
| `fundamentals.csv` | asset, report_date, **available_date**, book, earnings | 用报告期当日数据 = 前视偏差 |
| `universe.csv` | date, asset | 用今天的成分股回测五年前 = 幸存者偏差 |
| `calendar.csv` | date | 缺失日用行情日期当分母 → 整天消失也看不见 |
| `manifest.json` | sha256、rows、source、provider、adjust_mode、notes | 复现的前提；`notes` 记录停牌填充/时点口径 |

v1 合成样本是 v2 的子集；`load_panel` 认 v2：`adj_factor` 乘回价格、财报按 `available_date`
生效、`universe.csv` 按日生效。缺失单元格用前收盘填充并计入 `Panel.filled_rows`，同时写进
provenance。

### 9.3 三层职责

```
Provider（取数/翻译） → contract.write_snapshot（落盘 + 指纹）
                      → snapshot_check（体检） → load_panel（消费）
```

- `quant/providers/csv_import.py`：通用导入器，中英文表头、`YYYYMMDD`/`YYYY-MM-DD`、
  `--map 字段=列名`；缺 `available_date` 直接拒绝。
- `quant/providers/qmt.py`：QMT 只读适配器，**从不调用 `download_history_data`**；个人 QMT 已停用，
  脚本保留备查。
- `quant/providers/snapshot_check.py`：价格合法性、OHLC、重复行、指纹、日历覆盖率、
  财报公告日倒挂、时点成分覆盖；任何 fail 都不该进回测。
- `scripts/export_baostock_snapshot.py`：在带 baostock 的 Python 里导出 v2；默认时点成分，
  `--no-pit-universe` 退回当前名单。

### 9.4 Agent 2 的刷新流程

1. `list_snapshots` 找 `end` 最大且 `point_in_time=true` 的基线。
2. `refresh_snapshot(base_dir=…, out_dir=新目录, incremental=true)`；返回 `job_id`。
3. `refresh_status(job_id, wait_seconds=20~30)` 轮询到 `succeeded/failed`。
4. 成功后报告新 `dv`、目录、区间、标的数、体检结论；更新 `output/data/latest.json`。
5. Agent 1 用 `--latest` 接上；也可以 `--data-dir` 显式指定。

铁律：**不覆盖已有快照**；`out_dir` 必须新目录、全 ASCII；增量发现除权/修订会自动回退全量；
财报重述靠定期全量。

### 9.5 真实数据与合成数据的差异

最新真实快照 `dv-946b080b1258`（2019-01-02~2026-11-11，40 只时点成分，1905 天）。
同参数对照见 `output/reports/real_vs_synthetic.md`：固定池换成时点成分后，等权基准从
+7.94% 变成 -3.51%，约 11.5pp 是名单层面的幸存者偏差；合成数据里的“强动量”在真实数据上
没有延续。结论只作为数据质量/口径提醒，不构成任何策略有效性证据。

---

## 10. 已知技术债

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | 写作会话没有 sandbox 目录白名单 | `write` 能写工作区内任意文件 | profile 配 sandbox 白名单 |
| 2 | 合规扫描是正则 + 句内否定窗口 | 反讽、长分句可能漏判 | 草稿永远 `draft`，发布必须人工 |
| 3 | `srq-compat` 字段名自定义 | 接真实 SolidRockQuant 要逐项映射 | 先做字段对照表 |
| 4 | `manifest.sha256` 目前主要覆盖 `prices.csv` | 两个内容不同的快照可能 `dv` 相同 | 改成全文件哈希；复现时同时核对 `files.*.sha256` |
| 5 | 真实数据只有 baostock 单源 | 静默取错难发现 | 加双源交叉校验（收盘价偏差阈值） |
| 6 | 三个 profile 的 patch 是生成物 | 手改 profile 会漂移 | `acceptance.py` 已有“已安装 profile 与生成物一致”检查 |
| 7 | preset 只在 Web 表面可用，未端到端验证 | Web 选 preset 后工具面未实测 | 先 `--dump-config`，再在 GUI 手工确认 |
| 8 | 提示词里的文风规则只有一部分可机检 | “金句放段尾”等靠模型自觉 | `style_warnings` 已覆盖标题长度/我们/隐喻 |
| 9 | SmartX CLI 只能交互式运行，路径必须 ASCII | 无法把 CLI 调用自动化 | 走 GUI「选择上传」；所有文件放 ASCII 目录 |
| 10 | SmartX 自动导出是 6 个固定文件、整份覆盖 | 不能按“新文件”判断成交 | 按 `rowId` 对账，定时轮询 |
| 11 | `quant/data.py` 与 `quant/data/` 同名 | 在 `quant/data/` 放 `__init__.py` 会让 import 变成空包 | 绝不能放；适配器放 `quant/providers/` |

### 一个踩过的坑

`cordis.patch.yml` 的顶层条目是**按 id 的 patch**，不是新增；新条目必须放进 `- insert:`，
否则只得到 `patch: entry "xxx" not found` 的警告，组合看起来“成功”，实际什么都没加。
`cordis/phase1-presets.yml` 因此以 `- insert:` 形式生成，并用临时 Web profile 的
`--dump-config` 验证过。
