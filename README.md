# 杂灵根散修录 · 量化研究 Agent（Phase 1 + 数据/执行链路）

一个散户把“价值判断”写成可回测因子的公开实验。当前跑通三件事：

- **Agent 2**：把真实行情刷新成可复现快照（baostock → CSV → v2）；
- **Agent 1**：四字段研究指令 → 确定性回测 → 指标与实验 ID；
- **Agent 3**：技术文章写作 → 公众号草稿 / 知乎导出 → 人工发布。

执行侧停在 SmartX CSV 半自动：能生成订单 CSV、能自动导出对账，但下单确认必须人工点。
不是选股服务，不展示实时信号，不承诺收益，不推荐个股。这里是认知记录，不是工具橱窗。

| 想先看什么 | 去哪 |
|---|---|
| 怎么跑起来 | 本文「快速开始」 |
| 架构、假设、合规可达性分析 | [docs/architecture.md](docs/architecture.md) |
| 验收结论与已知限制（Phase 1 历史报告） | [docs/phase1-report.md](docs/phase1-report.md) |
| 策略规格与版本规则 | [docs/strategy.md](docs/strategy.md) |
| 公众号账号状态（接口权限、白名单、变现开通） | [docs/wechat-account.md](docs/wechat-account.md) |
| 平台发布（知乎导出、发布 SOP、记录） | [docs/platforms.md](docs/platforms.md) |
| 发布台（status / prepare / done） | [docs/publishing.md](docs/publishing.md) |
| 文章分类（量化研究 / AI技术 / 市场复盘 / 杂项） | [docs/article-categories.md](docs/article-categories.md) |

---

## 快速开始

```powershell
cd C:\AI_workspace\stock_agent_manager

# 0) 生成/校验合成样本数据（已提交，一般不需要重跑）
python tools\gen_sample_data.py

# 1) 自检：引擎 + 数据指纹
python -m quant.cli doctor

# 2) Agent 1 闭环：四字段研究指令 -> 回测 -> 指标 + 实验 ID
python scripts\run_agent1.py --instruction examples\research_instruction.json
#    等价的 CLI 写法（--dry-run 只做契约解析，不回测）
python -m quant.cli research --spec-file examples\research_instruction.json --dry-run

# 2b) Agent 2：刷新真实行情快照（需 NFR_BAOSTOCK_PYTHON / NFR_SNAPSHOT_ROOT）
dsh --profile agent2 "用最新的快照增量刷新到今天"
#    刷新完成后，Agent 1 用 --latest 接最新快照
python scripts\run_agent1.py --instruction examples\research_instruction_hs300.json --latest

# 3) 直接跑引擎（输入是内部 spec，不是四字段契约，用于复现/调试）
python -m quant.cli backtest --spec-file examples\research_momentum.json

# 4) MCP 协议级自检（真的 spawn 服务端走 JSON-RPC）
python scripts\verify_mcp.py

# 5) 公众号草稿接口预检（第一行只有两种结论）
python scripts\check_wechat_draft.py
#    CI / Router 用法：不可用时返回非零
python scripts\check_wechat_draft.py --require-available --json

# 5b) 推草稿进草稿箱（只到 draft/add，没有发布能力）
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\[杂项_001] 2026-11-07-opening.md --cover output\articles\cover-opening-2.35x1.png
#    原地改已有草稿的封面/正文（不新建）
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\[杂项_001] 2026-11-07-opening.md --cover <图片> --update-media-id <草稿ID>

# 6) Agent 3 降级路径：带 front matter 的 Markdown
python -m agents.agent3 --brief examples\brief_demo.json

# 6b) 知乎导出：只生成可粘贴稿 + 人工清单，不发布
python -m writing.export --all

# 7) 一键验收（14 项）
python scripts\acceptance.py

# 8) 回归测试（215 项）
python -m unittest discover -s tests -t .

# 9) 发布台：状态 / 卡片 / 回填（不发布）
python scripts\publish.py status
python scripts\publish.py prepare <slug> --platform zhihu
python scripts\publish.py done --platform zhihu <slug> --url <URL>
```

真实行情接入（换数据源只换 CSV，不改引擎）：

```powershell
# 行情 CSV 至少要有：日期、代码、开盘、最高、最低、收盘、成交量
# 可选：复权因子（不复权价 + 因子，或直接用复权价并把 adjust-mode 设对）
# 把任意来源的日线 CSV 归一化成 schema v2 快照，并立即体检
python -m quant.providers.csv_import --prices raw\prices.csv --out snapshots\first ^
    --universe csi300 --source "通达信日线导出" --adjust-mode backward
# 中英文表头都认；列名对不上就显式指定（可重复）
python -m quant.providers.csv_import --prices raw\prices.csv --out snapshots\first ^
    --universe csi300 --map 收盘价=close --map 股票代码=asset

# 让引擎读这份快照（默认仍读仓库里的合成样本）
$env:NFR_DATA_DIR = "snapshots\first"
python -m quant.cli doctor
```

有 baostock 的 Python（例如 SmartX 客户端自带的 `bin\cpython\python.exe`）可以直接拉真实日线
并生成 v2 快照：

```powershell
python scripts\export_baostock_snapshot.py --out snapshots\real40 ^
    --universe hs300_40 --index hs300 --sample 40 ^
    --start 2019-01-01 --end 2024-12-31 --fundamentals
```

脚本只依赖 baostock，仓库本身仍是纯标准库（baostock 只在 main() 里 import）。默认按**时点成分**
取样（每月末查一次 HS300 名单，按返回的 `updateDate` 前向填充），`--no-pit-universe`
可退回“当前名单”。成分口径会写进 `manifest.notes`。

真实数据的**登记实验统一走 Agent 1**（与写文章统一走 Agent 3 同理）：

```powershell
python scripts\run_agent1.py --instruction examples\research_instruction_hs300.json --latest
```

`--latest` 读 Agent 2 刷新的最新快照指针（`output\data\latest.json`）；也可以继续用
`--data-dir` 显式指定目录。两者只能选一个。

日常刷新可以走增量（重叠窗口校验，发现除权/修订自动回退全量），再一键跑 Agent 1：

```powershell
# 增量：基于上一份快照
powershell -ExecutionPolicy Bypass -File scripts\refresh_and_run.ps1 `
    -Base C:\AI_workspace\smartx_client\out\real40_pit `
    -Out C:\AI_workspace\smartx_client\out\real40_pit_20261111

# 全量
powershell -ExecutionPolicy Bypass -File scripts\refresh_and_run.ps1 `
    -Full -Out C:\AI_workspace\smartx_client\out\real40_pit_20261111
```

也可以直接用导出脚本：`--incremental --base-dir <旧快照>`，
默认拿最近 10 个交易日做重叠比对（`--overlap-days` 可调）。

QMT 只读导出（个人 QMT 已停用，以下仅历史备查）：

```powershell
# 先探本地能读到什么（不写文件）
python scripts\export_qmt_snapshot.py --probe --stocks 600000.SH,000001.SZ --start 20190101 --end 20241231
# 正式导出成 v2 快照并体检
python scripts\export_qmt_snapshot.py --stocks 600000.SH,000001.SZ --start 20190101 --end 20241231 ^
    --out snapshots\qmt --universe csi300 --universe-file raw\universe.csv
```

注意：sidecar 要跑在能 `import xtquant` 的那个 Python 里（QMT 安装目录下，或 pip 装的
`xtquant`）。若券商只允许在客户端进程内运行，就用终端手工导出 CSV，再走上面的 `csv_import`。

券商抽象层演示（只记账，不碰真钱）：

```powershell
python scripts\broker_demo.py

# Agent 提出下单提案后，人工在终端批准（唯一的批准入口）
python -m quant.broker.approve <提案ID>

# 真实数据快照体检（schema v2；不通过就别拿去回测）
python scripts\check_snapshot.py <快照目录>

# SmartX 下单 CSV：先抓不复权价，再生成（客户端「选择上传」与「下单」仍由人点）
python scripts\fetch_quotes.py --symbols 601939.SH --out output\broker\quotes.json
python scripts\make_smartx_csv.py --proposal <提案ID> --account <资金账号> --quotes output\broker\quotes.json

# SmartX 自动导出对账（只读，不产生订单；--archive 另存一份带时间戳的快照）
python scripts\reconcile_smartx.py --dir C:\AI_workspace\smartx_client\out\orders --archive
```

SmartX「设置 → 自动导出设置」每 120 秒把 6 个 CSV 整份覆盖到导出目录。仓库按
`rowId` 把委托对回提案，列出已成交/已撤/已拒绝/未匹配；下单确认仍需人工点。

DSH 侧（手动触发、不常驻）。`dsh` 需要能直接调用；若不在 PATH，用
`C:\Users\<you>\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd`。

```powershell
# 安装三个 profile（量化 / 数据运维 / 写作），幂等，可重复执行
python tools\build_cordis.py
python tools\install_dsh_profile.py

# Agent 1：会真实调用 mcp__srq__* 工具；没有 shell
dsh --profile quant "研究问题：过去一年涨幅靠前的是否继续走强。池子 synthetic_40，区间 2020-01-02~2024-12-31。"

# Agent 2：数据运维；只刷新/体检，不跑回测、不下单
dsh --profile agent2 "用最新的快照增量刷新到今天"

# Agent 3：工作区是 C:\AI_workspace\wechat_writing；工具表里没有量化工具
cd C:\AI_workspace\wechat_writing
dsh --profile writing "读 briefs\001-factor-to-backtest.json，写一篇文章到 articles\"
```

---

## 输入契约

Agent 1 对外只接受四个字段（任务书 3.2）：

```json
{
  "question": "过去一年涨幅靠前的标的，接下来一个月是否继续走强？",
  "universe": "synthetic_40",
  "period": "2020-01-02~2024-12-31",
  "factor_logic": "过去 12 个月的动量：涨幅靠前的标的在接下来一个月是否延续强势"
}
```

`factor_logic` 是自然语言，由 `quant/instruction.py` 的**关键词表**确定性地映射成引擎因子，
映射明细随结果返回（`contract.mapping`）。模型没有 `factor` 参数可填——否则它就决定了回测跑什么，
等于间接进入盈亏回路。歧义时直接报 `FACTOR_AMBIGUOUS`，不猜。

可选覆盖项：`rebalance` / `top_k` / `cost_bps` / `seed` / `data_version`。
`universe` 支持 `synthetic_40` 和 `沪深300`；后者映射到快照里的 `hs300_40_pit` 时点成分。
实际池子不存在、或快照缺时点成分时，明确报 `UNIVERSE_UNAVAILABLE`，不会假装回测。

可选覆盖之外，`python -m quant.cli backtest` 用的是**内部 spec**（`factor/start/end`），
仅用于复现和调试，不是对外契约。

---

## 架构

```
                  ┌──────────────────────────────┐
                  │ Agent 2（profile: agent2）   │
                  │ data-ops：刷新/体检快照      │
                  └───────────────┬──────────────┘
                                  │ snapshots + output/data/latest.json
                                  ▼
四字段研究指令 ──▶ ┌──────────────────────────────┐
question/universe   │ Agent 1（profile: quant）    │
period/factor_logic │ srq：research 10 / full 14   │
                    │ 只编排，不计算               │
                    └───────────────┬──────────────┘
                                    │ 指标 / 实验 ID / experiments/
                                    ▼
写作简报 ──▶ Agent 3（profile: writing）──▶ 文章 + 平台版本
             无量化工具、无发布能力          │
                                             ▼
                                发布台（scripts/publish.py）
                                status / prepare / done
                                             │
                          微信草稿箱 / 知乎导出（无发布）
                                             │
                                        人手动发布
```

两条写作路径，成文稿落在同一个地方：

- **默认：DSH 写作会话**（`dsh --profile writing`）负责成文；
- **确定性渲染**（`python -m agents.agent3`）只用于重渲染已有简报、格式修订与合规检查。

两者的产物都写到写作工作区 `C:\AI_workspace\wechat_writing\articles\`（`writing/article.py::ARTICLE_DIR`，
可用 `WFR_ARTICLES_DIR` 覆盖）。仓库 `output/articles/` 只剩封面素材与导出物；验收渲染的副本在
`output/reports/acceptance_article/`。

写完到发布之间，仓库侧有这些入口：

```powershell
# 推草稿：封面按栏目自动取（读 output/articles/covers/manifest.json），成功后写账本
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\<文章>.md --category 量化研究 --commit

# 发布后回写：改 front matter、追加 CHANGELOG、git 提交
python scripts\mark_published.py <slug> --ai-declared AI创作

# 发布台：状态 / 卡片 / 回填（只读写本地文件，不发布）
python scripts\publish.py status
python scripts\publish.py prepare <slug> --platform zhihu
python scripts\publish.py done --platform zhihu <slug> --url <URL>

# 单独提交工作区（改了正文但还没推时用）
python scripts\commit_articles.py -m "量化研究 004：补数据源一节"
```

账本 `output\reports\drafts.jsonl` 是"这篇文章在哪个草稿"的权威记录，每次推送追加一行；
合规结果落在 `output\reports\compliance-<slug>.json`。

关键不变量：

| 约束 | 怎么保证 |
|---|---|
| LLM 不进入盈亏计算 | 净值只由 `quant/engine.py` 计算；模型没有算账代码，也拿不到净值序列（`get_experiment` 默认不带 series） |
| 因子不由模型选择 | 四字段契约 + 服务端关键词表，模型没有 `factor` 参数 |
| 防前视偏差 | 调仓日 t 的因子只用 t-1 及以前数据；`signal_date = fill_date - 1 交易日`，有测试守着 |
| 可复现 | 无随机数、无 wall clock；`nav_hash` 覆盖整条净值序列；实验 ID 由 spec+数据指纹算出 |
| 数据刷新单入口 | 只有 Agent 2 的 `data-ops`（或人工 `refresh_and_run.ps1`）写快照；Agent 1 只读 |
| 执行隔离 | 没有程序化下单适配器；`PaperBroker` 之外没有真实 Broker；SmartX CSV 只生成文件，上传/确认由人 |
| 无自动发布 | 写作服务端只有 3 个草稿工具；另有本地导出/发布台；无 `freepublish`、无浏览器、无知乎写接口 |

---

## 目录

| 路径 | 作用 |
|---|---|
| `quant/` | 量化内核 + 数据运维：四字段契约、spec、数据、因子、引擎、实验登记、MCP（srq / data-ops）、CLI |
| `quant/data/` | 合成样本数据快照 + sha256 清单（真实快照在外部目录，通过 `NFR_DATA_DIR` / `--latest` 接入） |
| `quant/providers/` | v2 快照：CSV 导入、QMT 只读、快照体检、契约 |
| `quant/broker/` | `PaperBroker` + 提案/批准 + SmartX CSV 生成/导出对账；无真实 Broker 适配器 |
| `writing/` | 文章渲染、合规、草稿客户端、知乎导出、发布台、草稿 MCP（**不 import quant**） |
| `shared/` | 中立 MCP stdio 协议实现，两侧共用 |
| `agents/` | Agent 1 / Agent 3 的 Python 编排；Agent 2 由 profile + `quant/data_mcp.py` 组成 |
| `cordis/` | `prompts/`（三个 Agent 的提示词单一来源）、`profiles/`（quant / agent2 / writing） |
| `scripts/` | Agent 1/2 入口、CSV/baostock 导出、SmartX 工具、发布台、验收、MCP 自检 |
| `config/` | `agent2.example.json`（数据刷新配置）、`publishing.json`（发布默认值）；均不含凭据 |
| `tools/` | 数据生成、封面生成、Cordis 生成与安装、asar 读取器 |
| `examples/` | 四字段研究指令、内部 spec、写作简报示例 |
| `experiments/` | 公开实验记录；个股代码在 `experiments/.private/`（gitignore） |
| `output/` | `reports/`、`articles/`（文章与知乎导出）、`data/latest.json` 指针、`evidence/`、`broker/` |
| `tests/` | 215 项回归测试 |
| `bin/srq.cmd` | `srq mcp serve` 兼容入口（纯 ASCII 批处理） |

---

## 三套 Agent 怎么隔离

| 维度 | Agent 1（quant） | Agent 2（agent2） | Agent 3（writing） |
|---|---|---|---|
| DSH profile | `~/.dsh/profiles/quant` | `~/.dsh/profiles/agent2` | `~/.dsh/profiles/writing` |
| 工作区 | `C:\AI_workspace\stock_agent_manager` | 同左 | `C:\AI_workspace\wechat_writing` |
| MCP 服务端 | `srq`（research 模式 10 个工具；完整模式 14 个） | `data`（6 个：列快照/刷新/状态/取消/清理/体检） | `draft`（3 个工具） |
| shell / subagent / workflow / web | 全部关闭 | 全部关闭 | 全部关闭 |
| 实测工具数 | 20 | —（按 profile 生成物） | 12 |
| 系统提示词 | `cordis/prompts/agent1.md` | `cordis/prompts/agent2.md` | `cordis/prompts/agent3.md`（人设 + 文风 + 固定免责声明） |
| 发布能力 | —— | 不存在 | 不存在 |

三个 profile 的 patch 由 `tools/build_cordis.py` 从同一份提示词生成，避免手改漂移。
实测证据：quant 会话真实发出 `mcp__srq__run_research_instruction` 并复述实验 ID；
writing 会话回答 `NO_SRQ_TOOL`，但能调 `mcp__draft__wechat_probe_draft`。
Agent 2 的工具面由 `quant/data_mcp.py` 定义，只做数据刷新与体检，不跑回测。

Agent 2 成功后除了写快照，还会更新 `output\data\latest.json` 指针（dv / 目录 / 区间），
Agent 1 用 `--latest` 直接接上。发布用的实验记录只保留脱敏持仓（无个股代码），
代码在 `experiments\.private\`（gitignore）。

Agent 2 优先读仓库里的 `config/agent2.json`（已 gitignore，示例见
`config/agent2.example.json`），其次读环境变量：

```powershell
$env:NFR_BAOSTOCK_PYTHON = "C:\Users\ADMIN\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
$env:NFR_SNAPSHOT_ROOT = "C:\AI_workspace\smartx_client\out"
dsh --profile agent2 "用最新的快照增量刷新到今天"
```

---

## 与项目简报的偏差（重要）

六处与简报假设不一致，均已按实际调整，细节见 [docs/architecture.md](docs/architecture.md) 第 5 节：

1. **`srq` / SolidRockQuant 不存在**（机器上没有，PyPI 也不可达）→ 按约定工具面自建
   `srq-compat` MCP 服务端，命令仍是 `srq mcp serve`，工具名与简报一致。它**不是** SolidRockQuant，
   接真机时字段需要逐项核对。
2. **`deepseek-harness-sdk` 不存在** → 控制平面改用 `dsh` CLI + `agents/mcp_client.py`；
   仓库主链路零第三方依赖。
3. **数据不再只有合成样本**：合成锚 `dv-572bafec2a92` 仍用于回归；真实 baostock 快照
   `dv-946b080b1258` 已跑通（40 只 × 1905 天、时点成分）。QMT 对个人已停用，数据侧改走
   baostock/CSV，与券商解耦。
4. **`dsh headless` 不消费 agent preset**（源码硬限制）→ 用 profile 级隔离；
   preset 形态保留给 Web 会话，未在 Web 上端到端实测。
5. **`factor_logic` 由代码映射，不由模型选择** → 否则模型就决定了回测跑什么。
6. **执行侧不是 QMT 自动化**：miniQMT 对个人停用，SmartX Python 组件是沙箱；可用的是
   SmartX CSV 半自动（生成 CSV → 人工上传/确认 → 自动导出对账），**没有程序化下单适配器**。

---

## 合规红线怎么落地

- 名称自检：`writing.compliance.check_name`，拦截"股票/证券/投资/理财/基金/荐股/选股/牛股/涨停/量化选股"。
- 正文闸门：`article_compliance` 支持否定语境（"不推荐个股"放行），拦住荐股、买卖信号、
  收益承诺话术和 6 位个股代码。
- 两句硬性文本逐字校验：文末风险提示 `本文仅为个人研究记录…决策需独立。`；
  `data_source=synthetic` 时正文还必须出现 `前期回测基于合成数据…策略有效性证据。`
  （纯工程/方法稿可用 `data_source: none`：不含任何回测数字，因此不强制合成数据声明。）
- 口述整理稿（front matter `ai_assisted: true`）必须逐字含 AI 披露句
  `本文由我口述、AI 协助整理，观点与判断由我负责。`（`writing/compliance.py::AI_DISCLOSURE`），缺句判违规。
  平台侧的「AI 声明」不在 OpenAPI 字段里，另需在编辑器手动勾，见 `docs/wechat-account.md` §3.6。
- 文风自检（标题 ≤20 字、"我们"不多于"我"、修仙隐喻 ≤3 处）只出 warning，不拦发布。
- 被拒的文章写入 `output/rejected/`，不进正式目录。
- Agent 3 的系统提示词里固定了免责声明原文，且工具表里没有发布能力。

---

## 尚未实现 / 下一阶段

- **执行**：SmartX CSV 半自动已落地（生成 CSV、人工上传/确认、自动导出对账）；
  缺 `SmartX CSV → Broker` 适配器、免确认流程和程序化下单。实盘路线仍受 `AGENTS.md` B 节约束。
- **数据**：真实 baostock 快照已跑通；缺双源交叉校验、财报重述检测，以及 `manifest.sha256`
  从“主要覆盖 prices.csv”升级为全文件哈希。
- **发布**：发布台（`scripts/publish.py`）已落地；未做自动发布、浏览器自动化；Agent 4 未建。
- **Router / 常驻调度 / 自主派活**：未做；`agents/envelope.py` 只定义统一信封。
- **组合构建层**（多因子、权重、敞口上限）：未开始。
- **PaperBroker** 仍是唯一 Broker 实现；`run_paper_session` 可继续用于部署前验证。
