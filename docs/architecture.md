# 架构与合规可达性说明（Phase 1）

这份文档回答任务书第 0 节的三件事：**先列假设与不确定点**、**逐条确认禁止事项不可达**、
**指出与 DSH 实际能力的冲突并给替代方案**。第 3.1 节要求的分层设计与目录树也在这里。

---

## 1. 假设与不确定点（写代码前先确认的东西）

### 1.1 已验证（有命令、有证据）

| 项 | 结论 | 验证方式 |
|---|---|---|
| Python 版本 | 3.12.8（`C:\Program Files\Python312`） | `python --version` |
| DSH 版本 | Desktop 0.2.2-rc.1，`dsh` CLI 可用 | `dsh --help` |
| Cordis 配置加载 | 自定义 profile 可组合，`--dump-config` 成功 | `output/evidence/composed_config_*.txt` |
| MCP stdio 连接 | DSH 能 spawn 并连接本地 MCP 服务端 | stderr `[srq-compat] ready on stdio` |
| 工具面可见性 | 模型工具表里出现 `mcp__srq__*` / `mcp__draft__*` | `output/evidence/dsh_*_tool_call.jsonl` |
| 外网 | 仅 `api.deepseek.com` 可达；PyPI / 通用 HTTP 不可达 | `Invoke-WebRequest` 探测 |

### 1.2 与任务书假设冲突（已确认不成立）

| 任务书假设 | 实际 | 影响 |
|---|---|---|
| `deepseek-harness-sdk` 已安装 | **该包在 PyPI 上不存在**，本机也没有 | 控制平面不能按 Python SDK 写 |
| `solidrock-quant[mcp,sources]` 已安装、`srq init` 已跑 | **本机没有 `srq`，也装不了**（无网络） | 回测引擎必须换实现 |
| PyPI 可用来装依赖 | 不可达 | 全链路只能标准库 |
| `srq mcp serve` 暴露的工具名已知 | 无真机可对照 | 按简报第 4 节的 6 个名字自建，并额外加一个契约入口 |

### 1.3 仍然不确定（Phase 1 无法消除）

- **公众号 `draft/add` 是否可用**：没有凭据，只能给出 `DRAFT_API_UNAVAILABLE/NO_CREDENTIALS`。
- **真实 SolidRockQuant 的返回字段**：`srq-compat` 的字段名是我按简报自定的，接真机需要映射。
- **真实行情的可得性与授权**：当前只有合成样本。

---

## 2. 分层落地

```
┌──────────────────────────────────────────────────────────────┐
│ 控制平面（Python）                                             │
│   scripts/run_agent1.py      四字段指令 -> 信封                │
│   scripts/acceptance.py      验收                             │
│   agents/mcp_client.py       MCP stdio 客户端（协议层）        │
│   职责：构造指令、调用能力、收集结果。不计算任何指标。          │
└───────────────┬──────────────────────────────┬───────────────┘
                │ 进程内调用                     │ MCP stdio (JSON-RPC)
                ▼                               ▼
┌──────────────────────────────┐   ┌────────────────────────────┐
│ Agent 组合（Cordis 配置层）   │   │ 能力服务端                  │
│  cordis/profiles/quant.yml   │   │  quant/mcp_server.py       │
│  cordis/profiles/writing.yml │   │   - run_research_instruction│
│  cordis/prompts/*.md         │   │   - run_backtest ...       │
│  职责：决定"这个 Agent 能看   │   │  writing/draft_mcp.py      │
│  到什么工具、什么提示词"      │   │   - wechat_add_draft ...   │
└──────────────────────────────┘   └────────────────────────────┘
```

- **控制平面**：任务书要求 Python SDK。实际用 `scripts/run_agent1.py` + `agents/mcp_client.py`
  充当同一角色：构造指令、建立 MCP 连接、调用工具、收信封。`agents/envelope.py` 是唯一的
  结果契约，将来换成真 SDK 时只需要替换这一层，上层不用改。
- **Agent 组合**：写在 Cordis YAML 里（`cordis/profiles/*.yml`），由 `tools/build_cordis.py`
  从提示词生成，`tools/install_dsh_profile.py` 安装到 `~/.dsh/profiles/`。提示词是单一来源，
  避免"配置文件里的提示词"和"文档里的提示词"各说一套。
- **为什么用 YAML 而不是 JSON**：Cordis 的 patch 层原生是 YAML，支持 `insert` / `disabled` /
  `!!js` 表达式；用 JSON 会丢掉注释且无法表达 `!!js`。
- **工作区与 Session**：两个 profile 各自一个工作目录，session 由 `dsh` 每次新建。
  Agent 1 在仓库根（要读 experiments/），Agent 3 在 `C:\AI_workspace\wechat_writing`。
- **工具面隔离**：见第 4 节。

### 目录树

```
stock_agent_manager/
├─ quant/                       # 量化域（写作侧禁止 import）
│  ├─ instruction.py            # 四字段契约 -> spec（关键词表，不让模型选因子）
│  ├─ spec.py                   # 引擎 spec 校验
│  ├─ data.py                   # 数据快照 + sha256 校验
│  ├─ factors.py                # 4 个因子
│  ├─ engine.py                 # 确定性回测（净值、指标、IC）
│  ├─ experiments.py            # 实验登记簿
│  ├─ validate.py               # 回测前静态校验
│  ├─ paper.py                  # 模拟盘（历史回放，无实盘）
│  ├─ mcp_server.py             # srq-compat MCP 服务端（11 个工具）
│  ├─ cli.py / console.py       # srq CLI / UTF-8 输出
│  └─ data/                     # prices.csv + manifest.json（sha256）
├─ writing/                     # 写作域（禁止 import quant）
│  ├─ article.py                # front matter 渲染（确定性）
│  ├─ compliance.py             # 合规闸门（正则 + 否定语境 + 两句逐字声明）
│  ├─ wechat.py                 # 草稿接口客户端（无 freepublish）
│  ├─ drafts.py                 # 写草稿的唯一实现（agent3 与 draft_mcp 共用）
│  ├─ draft_mcp.py              # 草稿 MCP 服务端（3 个工具）
│  ├─ platforms/                # 平台导出（知乎），无发布能力
│  │  └─ zhihu.py
│  └─ export.py                 # 平台导出 CLI（只写文件，不联网）
├─ shared/mcp_stdio.py          # 中立协议层，两侧共用
├─ agents/                      # 编排层
│  ├─ agent1.py / agent3.py     # 两个 Agent 的闭环
│  ├─ mcp_client.py             # MCP 客户端
│  └─ envelope.py               # 统一输出信封（Router 的消费契约）
├─ cordis/
│  ├─ prompts/agent1.md, agent3.md   # 提示词单一来源
│  ├─ profiles/quant.yml, writing.yml # 生成物，安装到 ~/.dsh/profiles
│  └─ phase1-presets.yml        # preset 形态（Web 表面用）
├─ scripts/                     # run_agent1.py / check_wechat_draft.py / acceptance.py / verify_mcp.py
├─ tools/                       # 数据生成、Cordis 生成与安装、asar 读取器（构建期用）
├─ examples/                    # 四字段指令、内部 spec、写作简报
├─ docs/                        # 本文、验收报告、策略规格（strategy.md）
├─ tests/                       # 35 项回归测试
├─ bin/srq.cmd                  # srq 兼容入口（纯 ASCII 批处理）
├─ experiments/                 # 实验记录（公开日志）
└─ output/                      # reports / articles / evidence / rejected
```

---

## 3. 简报第 7 节：逐条可达性分析

| # | 禁止事项 | 架构上如何不可达 | 验证 |
|---|---|---|---|
| 1 | 不自动发布公众号；不调用 `freepublish`；不浏览器自动化 | 全仓库没有 `freepublish` 调用；写作 MCP 服务端只注册 3 个工具，没有发布工具；DSH 工具表实测 12 个工具无发布项；Web 搜索/浏览器工具已在两个 profile 中 `disabled: true` | `tests/test_writing.py::test_no_publish_surface`、`dsh` 工具表 |
| 2 | 不接实盘；不暴露 `live_submit_order`；无下单路径 | **当前事实**：没有任何真实券商适配器；下单工具只有 `broker_*` 四个，全部落在 `PaperBroker`（`live_orders: false`），且提交前必须有人工批准文件。**Agent 1 的未来路线**：本人账户实盘 + 自动化执行，条件见 `AGENTS.md` B 节（仅本人、仅量化 profile、审计落盘、先模拟后实盘）。**接入真实通道时**：`acceptance.py` 检查 7 会变红，届时必须改写而不是删掉 | `acceptance.py` 检查 7/9、`verify_mcp.py` 的 `broker_requires_human_approval` |
| 3 | 不向 Agent 3 暴露 `run_backtest` 等量化工具 | 写作 profile 的 patch 里没有任何 `dsh-mcp-client` 指向 srq；只有一个 draft 服务端。实测写作会话工具表 12 个，无 `mcp__srq__*` | `dsh_writing_no_quant_tool.jsonl`、`dsh_draft_tool_surface.jsonl` |
| 4 | 不让 LLM 生成回测净值 | 净值只在 `quant/engine.py` 产生；MCP 返回 `nav_hash` 与指标；模型侧没有算账代码，也不接收净值序列（`get_experiment` 默认 `include_series=false`） | `test_same_spec_same_nav_hash`、`verify_mcp.py` |
| 5 | 不把"AI 量化选股"写进名称或功能介绍 | `writing.compliance.check_name` 拦截 10 个词；文章合规扫描对 title + tags 也跑一遍 | `test_name_channel_words` |
| 6 | 不在 Phase 1 实现 Router 或自主调度 | 没有 Router 代码；`envelope` 只给 `handoff_eligible` 标记，没有任何触发器；两个 profile 都关闭了 subagent / workflow / schedule 相关工具 | 目录树中无 router 模块；工具表实测 |

### 3.1 「对内执行」与「对外表达」是两个平面

这是本项目最容易搞混、也最容易被要求"放宽一点"的地方。两者的规则不一样：

| | 对内执行（Agent 1，量化 profile） | 对外表达（Agent 3，写作 profile 及一切公开输出） |
|---|---|---|
| 个股代码 | ✅ 可以出现（持仓、订单草案） | ❌ 绝对不出现 |
| 买卖方向 | ✅ 可以出现（订单） | ❌ 不出现 |
| 收益表述 | 引擎指标，可陈述统计事实 | 不承诺收益、不写成"业绩" |
| 实盘下单 | 路线允许（仅本人账户，条件见 `AGENTS.md` B） | 不存在，也不该存在 |
| 发布 | 不涉及 | 只能到草稿，发布由人手动点 |

判断一个功能该不该做，先问它属于哪个平面，而不是问"这句话能不能说"。
同一句话在量化会话里是工作内容，写进公众号就是违规——这不是双标，是两面墙。

**仍然存在的缺口（不隐瞒）**：

- 写作 Agent 的 `write` 可以写它工作区内的任意文件；如果它拿到仓库绝对路径，理论上能写坏量化文件。
  这是工作区隔离而非安全边界。要收紧需要给 profile 配 sandbox 目录白名单——Phase 1 未做。
- 合规扫描是正则 + 否定窗口，不是语义审核；反讽和长分句可能漏判。所以草稿 `status: draft`，
  发布永远由人手动完成。

---

## 4. 两个 Agent 的工具面（实测）

| | Agent 1（quant） | Agent 3（writing） |
|---|---|---|
| MCP 服务端 | `srq`（11 个工具，含 4 个模拟下单） | `draft`（3 个工具） |
| 文件工具 | read/write/edit/glob/grep/read_image | 同左 |
| shell | **无** | **无** |
| subagent / workflow | **无** | **无** |
| web / 插件管理 | **无** | **无** |
| 量化工具 | 7 个 | **0 个** |
| 实测工具总数 | 20 | 12 |

共同关闭的能力由 `tools/build_cordis.py` 的 `DISABLED_TOOLS` 统一生成，避免两个 profile 漂移。

---

## 5. 与 DSH 实际能力的冲突及替代方案

### 冲突 1：Python SDK 不存在

- **现象**：任务书假设 `deepseek-harness-sdk` 已安装并作为控制平面；该包在 PyPI 上不存在，本机也没有。
- **替代**：控制平面用 `dsh` CLI（手动触发）+ `agents/mcp_client.py`（程序化调用）。
  两者走的是同一条 MCP 协议，能力等价。
- **代价**：没有 SDK 的 `Session` 对象，会话标识由 `dsh --json` 的 `session` 事件给出。
- **迁移缝**：`agents/envelope.py` 与 `agents/mcp_client.py` 是唯一需要替换的两处。

### 冲突 2：`dsh headless` 不消费 agent preset

- **现象**：`dsh-headless/lib/index.js:227` 明确规定，若 Session 记录在某个 preset 下，直接抛错
  "which the one-shot runner does not compose"。
- **替代**：Phase 1 用 **profile 级隔离**（两个 profile，各自一份 patch），已验证两个 profile 的
  组合结果不同、工具表不同。
- **保留**：`cordis/phase1-presets.yml` 仍按 preset 形态生成，供 Web 会话按会话选 preset 时使用。
- **代价**：headless 场景下"同一进程内两个 Agent"做不到，必须起两次进程。

### 冲突 3：SolidRockQuant 不存在

- **现象**：没有 `srq` 可执行文件，PyPI 也不可达。任务书要求"回测净值由 SolidRockQuant 确定性引擎计算"。
- **替代**：`srq-compat` 按简报第 4 节的 6 个工具名自建，命令仍是 `srq mcp serve`
  （`bin/srq.cmd`），引擎为纯 stdlib 确定性实现。
- **代价**：这不是 SolidRockQuant，不能声称等价；字段名和语义需要接真机时逐项核对。
- **迁移缝**：替换 `quant/data.py::load_panel` 与 `quant/engine.py` 的计算后端，工具面不变。

### 冲突 4（主动加的一条）：`factor_logic` 是自然语言，谁来决定跑哪个因子？

- **风险**：如果让模型看 `factor_logic` 自己挑因子，它就事实上决定了回测跑什么，进而影响盈亏，
  与"LLM 不进入盈亏计算回路"冲突。
- **方案**：契约解析与因子映射都在**服务端代码**里完成（`quant/instruction.py` 的关键词表），
  MCP 工具 `run_research_instruction` 只接受四字段；模型没有 `factor` 参数可填。
  歧义时直接报 `FACTOR_AMBIGUOUS`，不做猜测。
- **验证**：`tests/test_instruction.py`；`verify_mcp.py` 断言映射结果 `["momentum_12_1"]`。

---

## 6. 一致性矩阵（任务书条目 -> 实现 -> 证据）

| 任务书条目 | 实现 | 证据 |
|---|---|---|
| §0.1 先列假设与不确定点 | 本文第 1 节 | 本文 |
| §0.2 逐条确认禁止事项 | 本文第 3 节 | 本文 + 测试 |
| §0.3 冲突直接指出 | 本文第 5 节 | 本文 |
| §3.1 分层 + 目录树 | 本文第 2 节 | 本文 |
| §3.2 cordis 配置示例 | `cordis/profiles/quant.yml`、`cordis/phase1-presets.yml` | 文件 + `--dump-config` |
| §3.2 Python 入口脚本 | `scripts/run_agent1.py`（四字段契约） | `examples/research_instruction.json` |
| 四字段输入契约 | `quant/instruction.py` + MCP `run_research_instruction` | `tests/test_instruction.py` |
| LLM 不进入盈亏回路 | 因子映射在代码；净值在引擎 | `test_same_spec_same_nav_hash` |
| 工具面隔离 | 两个 profile 各自工具表 | `dsh_quant_tool_call.jsonl`、`dsh_draft_tool_surface.jsonl` |
| 手动触发、不常驻 | 每次 `dsh` 起一个进程跑一次 | `dsh_quant_tool_call.jsonl` 的 session/final 事件 |

---

## 7. 券商通道抽象层（当前只到 PaperBroker）

`quant/broker/` 定义的是**契约**，不是某家券商的 SDK 封装。目的是让调用方（组合构建、
部署验证）先对着接口写；等选定券商，只补一个适配器。

三道具名闸门在 `PaperBroker` 里就已经生效，真实适配器不得绕过：

| 闸门 | 实现位置 | 行为 |
|---|---|---|
| 人工确认 | `OrderRequest.human_confirmed` | 为假一律拒单（`NOT_CONFIRMED`）。模型不能自己填 true |
| 风控上限 | `RiskLimits` | 单笔名义金额、单日单数、单标的持仓上限、现金/持仓充足性 |
| 审计落盘 | `broker/ledger.py` | 每笔（含被拒的）追加一行 JSONL：时间、标的、方向、数量、价格、费用、实验 ID、确认标记 |

另外两条工程约束：

- **幂等**：同一 `client_order_id` 重复提交直接拒（`DUP_ORDER_ID`），防止重试造成重复下单。
- **限价单不猜价**：参考价取市场价，限价只做"是否触价"的闸；未触价就是 `PENDING`，
  不动资金，也不假装成交。

`PaperBroker` 是唯一实现：按数据快照收盘价成交，收取佣金（万 2.5，最低 5 元）与卖出印花税（千 1），
不联网、不读券商凭据。演示：`python scripts\broker_demo.py`。

### 7.1 Agent 怎么下单：三段式，人必须在环路里

MCP 暴露四个工具：`broker_account`、`broker_orders`（只读）、`broker_propose_order`、`broker_submit_order`。

```
Agent  broker_propose_order  ──▶  提案文件（不产生订单）
                                     │
人      python -m quant.broker.approve <提案ID>   ← 唯一的批准入口，需要 shell
                                     │ 写入批准记录（含提案内容 sha256）
Agent  broker_submit_order   ───────┘ 校验：批准记录 / 哈希 / 有效期 / 是否已提交
```

为什么这个闸门不是装饰：

- **量化 profile 没有 shell**（见第 4 节工具面），所以 Agent 自己跑不了 `approve`；
- 批准记录绑定的是**提案内容的 sha256**，批准后改数量、改标的都会失效；
- 提案一次性：提交过就打标记，重复提交返回 `ALREADY_SUBMITTED`；
- 提案默认 30 分钟过期。

账户状态落在 `output/broker/paper_state.json`，跨会话保留；订单以追加式账本 `paper_orders.jsonl` 为准。

**尚未实现**：任何真实券商适配器。接入前需要解决的四件事写在 `AGENTS.md` B 节
（仅本人账户、能力只在量化 profile、凭据隔离、先模拟后实盘）。

---

## 9. 数据接入（真实行情的入口）

现状：只有合成数据。接真实行情的骨架已经就位，但**还没有任何真实数据进过系统**。

### 9.1 为什么先做契约，而不是先写抓取

`quant/data.py::load_panel()` 是唯一入口，engine / factors / paper / broker 都只认 `Panel`。
所以接数据的正确顺序是：**先定"快照长什么样"，再让各家数据源去填**。
否则每接一家就改一次引擎，第三次就没人敢动了。

### 9.2 快照规范（schema v2）

| 文件 | 字段 | 为什么必须有 |
|---|---|---|
| `prices.csv` | date, asset, open, high, low, close, volume, **adj_factor** | 不复权价算收益，除权日就是假跌停 |
| `fundamentals.csv` | asset, report_date, **available_date**, book, earnings | 用报告期当日数据 = 前视偏差 |
| `universe.csv` | date, asset | 用今天的成分股回测五年前 = 幸存者偏差 |
| `calendar.csv` | date | 缺失日用行情日期当分母 → 整天消失也看不见 |
| `manifest.json` | sha256、rows、source、provider、adjust_mode、notes | 复现的前提；`notes` 记录停牌填充了多少 |

v1（现有合成数据）是 v2 的子集，缺什么补默认值，所以旧快照不受影响。

消费端（`load_panel`）已经认这套 v2：`adj_factor` 乘回价格、财报按 `available_date`
生效（公告前是 NaN，不给假分数）、`universe.csv` 按日生效（当日成分之外不参与排名）。
缺失的 (date, asset) 单元格用前收盘填充并计入 `Panel.filled_rows`，同时写进实验
provenance——填充是让面板保持矩形的兜底，不是免责声明；补数据仍然是 Provider 的责任。

### 9.3 三层职责

```
Provider（取数、翻译）  →  contract.write_snapshot（落盘 + 指纹）
                          →  snapshot_check（体检）  →  load_panel（消费）
```

- `quant/providers/qmt.py`：券商 QMT / xtquant 适配器，**未在本机验证**（本机没装终端）。
  只调用读接口（`get_market_data_ex` / `get_trading_dates`），**从不调用 `download_history_data`**；
  取后复权价、停牌按前收盘填充并计数、财报接口故意不自动实现（字段名因券商而异，写错不报错只静默为空）。
- `scripts/export_qmt_snapshot.py`：sidecar 入口，`--probe` 只报告本地能读到什么、不写文件；
  导出模式直接落 v2 快照并跑体检。`tests/test_qmt_sidecar.py` 用假 xtquant 钉住"只读"这条性质。
- `quant/providers/csv_import.py`：**通用导入器**，不取数，只把任意 CSV 翻译成 v2。
  中英文表头、`YYYYMMDD`/`YYYY-MM-DD` 都认，`--map 字段=列名` 可覆盖，行序不影响 sha256。
  缺 `available_date` 直接拒绝——宁可导不进来，也不要一份前视偏差的快照。
- `quant/providers/snapshot_check.py`：价格合法性、OHLC 关系、重复行、指纹一致性、
  **以日历为分母的覆盖率**、财报公告日倒挂、**时点成分是否覆盖每个交易日**。任何 fail 都不该进回测。
- `scripts/check_snapshot.py <目录>`：给人用的体检入口。

快照来源由 `load_panel(dir)` 或环境变量 `NFR_DATA_DIR` 决定；默认仍是仓库里的合成样本，
所以"换数据"不需要覆盖 `quant/data/`，也不需要改引擎。

### 9.4 一个目录陷阱

`quant/data.py`（模块）与 `quant/data/`（数据文件目录）同名共存。
**绝对不能在 `quant/data/` 里放 `__init__.py`**——放进去它就成了包，`import quant.data`
会去加载空包，整个项目起不来。适配器因此放在 `quant/providers/`。

### 9.5 数据源与交易通道已经解耦（2026-11）

券商侧的政策变化：QMT 客户端自 2026-10-23 起限制**读写本地文件、与外部网站交互、
在服务器上运行**，但**程序化下单不受影响**（社区记录：<https://www.jisilu.cn/question/526075>）。

这条变化只打中"取数"，打不中本项目的架构：

- 行情侧：交换的是 `Provider`，契约与引擎不动。任何能落成 CSV 的来源（通达信本地日线、
  公开接口、baostock、付费数据商、手工导出）都走 `csv_import` 进同一套快照。
- **终端已下载的数据仍可读**（用户已确认）：`scripts/export_qmt_snapshot.py` 只读导出，
  不调用下载接口。先 `--probe` 看本地有什么，再正式导出。
- 交易侧：`Broker` 是另一条接口。若 `xttrader` 仍可用，Phase 2 照常实现；数据不再来自 QMT 不影响下单。
- 因此"能不能导出日线"不再是项目的分水岭；分水岭变成"能不能拿到一份可复现的日线文件"，
  而这件事现在与券商无关。

**边界**：sidecar 必须跑在能 import `xtquant` 的那个 Python 里。若券商只允许在客户端进程内
运行，就退回"终端内手工导出 CSV → `csv_import`"，两条路落的是同一套契约。

**不做什么**：不绕过 QMT 的文件/网络限制（改配置、注入、代理）。那是券商协议与监管问题，
代价可能落在账户上；正确方向是换数据源。

**还没做**：双源交叉校验（同一区间用两个来源比收盘价，偏差超过阈值就 fail）。
免费数据源最大的风险不是取不到，是**静默取错**；接真实数据前值得加这一道。

---

## 10. 已知技术债

按"会不会咬人"排序，不是待办清单的完整版。

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| 1 | 写作会话没有 sandbox 目录白名单 | `write` 能写工作区内任意文件；拿到绝对路径可越界 | profile 里配 sandbox 白名单，或在 Phase 2 用独立目录树 |
| 2 | 合规扫描是正则 + 句内否定窗口 | 反讽、长分句否定可能漏判 | 草稿永远 `status: draft`，发布必须人工；后续可加规则单测语料 |
| 3 | `srq-compat` 字段名是自定义的 | 接真实 SolidRockQuant 要逐项映射 | 先写一份字段对照表，再做适配层 |
| 4 | 数据是合成样本 | 任何收益结论都不可外推 | 保持 `data_source` 字段透出，接真实数据前不写"结论"类文章 |
| 5 | 两个 profile 的 patch 是生成物，但没进 CI | 手改 profile 会与仓库漂移 | 已在 `acceptance.py` 加"已安装 profile 与仓库生成物一致"的校验 |
| 6 | preset 只在 Web 表面上可用，未做端到端验证 | Web 上按会话选 preset 后工具面未实测 | 先用 `--dump-config` 验证组合（已做），再在 GUI 里手工选一次确认 |
| 7 | 提示词里的文风规则只有一部分可机器校验 | "金句放段尾""修仙隐喻 ≤3 处"靠模型自觉 | `style_warnings` 已覆盖标题长度、"我们/我"、隐喻次数；其余接受 |
| 8 | `dsh` 不在 PATH 时要写全路径 | 文档/脚本易踩 | README 已注明；后续可在 `bin/` 加 `dsh.cmd` 转发 |
| 9 | 知乎版 HTML 粘贴未实测 | 编辑器可能不认语义 HTML，格式需手工修 | 先手工发一篇，把结论写回 `docs/platforms.md` |

### 一个踩过的坑（写下来免得再犯）

`cordis.patch.yml` 的顶层条目是**按 id 的 patch**，不是新增：新条目必须放在 `- insert:` 列表里，
否则只会得到 `patch: entry "xxx" not found` 的警告，而组合看起来"成功"——实际上什么都没加进去。
`cordis/phase1-presets.yml` 因此以 `- insert:` 形式生成，并用一个临时 Web profile 的
`--dump-config` 验证过（产物见 `output/evidence/composed_config_presets_web.txt`）。
