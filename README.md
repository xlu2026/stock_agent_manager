# 杂灵根散修录 · 量化研究 Agent（Phase 1）

一个散户把"价值判断"写成可回测因子的公开实验。这一期只做**最小可验证闭环**：
结构化研究指令 → 确定性回测 → 指标与实验 ID；以及公众号文章的 Markdown 草稿降级路径、
知乎导出（只导出，不发布）。

不是选股服务，不展示实时信号，不承诺收益，不推荐个股。这里是认知记录，不是工具橱窗。

| 想先看什么 | 去哪 |
|---|---|
| 怎么跑起来 | 本文「快速开始」 |
| 架构、假设、合规可达性分析 | [docs/architecture.md](docs/architecture.md) |
| 验收结论与已知限制 | [docs/phase1-report.md](docs/phase1-report.md) |
| 策略规格与版本规则 | [docs/strategy.md](docs/strategy.md) |
| 公众号账号状态（接口权限、白名单、变现开通） | [docs/wechat-account.md](docs/wechat-account.md) |
| 平台发布（知乎导出、发布 SOP、记录） | [docs/platforms.md](docs/platforms.md) |
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

# 3) 直接跑引擎（输入是内部 spec，不是四字段契约，用于复现/调试）
python -m quant.cli backtest --spec-file examples\research_momentum.json

# 4) MCP 协议级自检（真的 spawn 服务端走 JSON-RPC）
python scripts\verify_mcp.py

# 5) 公众号草稿接口预检（第一行只有两种结论）
python scripts\check_wechat_draft.py
#    CI / Router 用法：不可用时返回非零
python scripts\check_wechat_draft.py --require-available --json

# 5b) 推草稿进草稿箱（只到 draft/add，没有发布能力）
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\2026-11-07-opening.md --cover output\articles\cover-opening-2.35x1.png
#    原地改已有草稿的封面/正文（不新建）
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\2026-11-07-opening.md --cover <图片> --update-media-id <草稿ID>

# 6) Agent 3 降级路径：带 front matter 的 Markdown
python -m agents.agent3 --brief examples\brief_demo.json

# 6b) 知乎导出：只生成可粘贴稿 + 人工清单，不发布
python -m writing.export --all

# 7) 一键验收（11 项）
python scripts\acceptance.py

# 8) 回归测试（110 项）
python -m unittest discover -s tests -t .
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

有 QMT 终端、且本地已经下载过行情时，可以只读导出（不联网、不下载）：

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
```

DSH 侧（手动触发、不常驻）。`dsh` 需要能直接调用；若不在 PATH，用
`C:\Users\<you>\AppData\Local\Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd`。

```powershell
# 安装两个 profile（量化 / 写作），幂等，可重复执行
python tools\build_cordis.py
python tools\install_dsh_profile.py

# Agent 1：会真实调用 mcp__srq__* 工具；没有 shell
dsh --profile quant "研究问题：过去一年涨幅靠前的是否继续走强。池子 synthetic_40，区间 2020-01-02~2024-12-31。"

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
`universe` 目前只支持 `synthetic_40`；写 `沪深300` 会明确报 `UNIVERSE_UNAVAILABLE`，不会假装回测。

可选覆盖之外，`python -m quant.cli backtest` 用的是**内部 spec**（`factor/start/end`），
仅用于复现和调试，不是对外契约。

---

## 架构

```
        四字段研究指令 ───▶ ┌──────────────────────────────┐
   question/universe/       │  Agent 1（profile: quant）    │
   period/factor_logic      │  只做编排，不做计算            │
                            └──────────────┬───────────────┘
                                           │ MCP stdio (JSON-RPC)
                                           ▼
                            ┌──────────────────────────────┐
                            │ srq-compat MCP server         │
                            │ run_research_instruction      │
                            │ run_backtest / validate_...   │
                            │ 关键词表映射 + 确定性引擎      │
                            └──────────────┬───────────────┘
                                           │ 只读
                                           ▼
                            ┌──────────────────────────────┐
                            │ quant/data/prices.csv         │
                            │ + manifest.json（sha256 指纹）│
                            └──────────────────────────────┘

   写作简报 ──▶ Agent 3（profile: writing）──▶ 工作区 articles/*.md
                无量化工具、无发布能力        └▶ 草稿箱（有凭据 + 封面素材时）
```

两条写作路径，成文稿落在同一个地方：

- **默认：DSH 写作会话**（`dsh --profile writing`）负责成文；
- **确定性渲染**（`python -m agents.agent3`）只用于重渲染已有简报、格式修订与合规检查。

两者的产物都写到写作工作区 `C:\AI_workspace\wechat_writing\articles\`（`writing/article.py::ARTICLE_DIR`，
可用 `WFR_ARTICLES_DIR` 覆盖）。仓库 `output/articles/` 只剩封面素材与导出物；验收渲染的副本在
`output/reports/acceptance_article/`。

写完到发布之间，仓库侧有三个脚本：

```powershell
# 推草稿：封面按栏目自动取（读 output/articles/covers/manifest.json），成功后写账本
python scripts\push_draft.py --file C:\AI_workspace\wechat_writing\articles\<文章>.md --category 量化研究 --commit

# 发布后回写：改 front matter、追加 CHANGELOG、git 提交
python scripts\mark_published.py <slug> --ai-declared AI创作

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
| 实盘隔离 | Phase 1 无任何下单实现；实盘路线只对 Agent 1 开放且仅限本人账户，与对外表达完全分离 |
| 无自动发布 | 写作服务端只有 3 个草稿工具，没有发布接口；全仓库无 `freepublish` 调用 |

---

## 目录

| 路径 | 作用 |
|---|---|
| `quant/` | 回测内核：四字段契约、spec、数据、因子、引擎、实验登记、MCP 服务端、CLI |
| `quant/data/` | 合成样本数据快照 + sha256 清单 |
| `quant/broker/` | 券商通道契约（`Broker`）+ `PaperBroker`；无真实适配器，见架构文档第 7 节 |
| `writing/` | 文章渲染、合规扫描、草稿客户端、平台导出（知乎）、草稿 MCP 服务端（**不 import quant**） |
| `shared/` | 中立 MCP stdio 协议实现，两侧共用，不放业务逻辑 |
| `agents/` | Agent 1 / Agent 3 编排、MCP 客户端、统一输出信封 |
| `cordis/` | `prompts/`（提示词单一来源）、`profiles/`（生成的两个 profile patch）、`phase1-presets.yml` |
| `scripts/` | 验收、MCP 自检、草稿接口预检、Agent 1 入口脚本 |
| `tools/` | 数据生成、封面生成、Cordis 生成与安装、排查 DSH 用的 asar 读取器 |
| `examples/` | 四字段研究指令、内部 spec、写作简报示例 |
| `experiments/` | 实验记录（公开日志，每条带 spec/数据指纹/nav_hash） |
| `output/` | `reports/` 汇报、`articles/` 文章与知乎导出（`articles/zhihu/`）、`evidence/` 验收证据 |
| `tests/` | 回归测试 |
| `bin/srq.cmd` | `srq mcp serve` 兼容入口（纯 ASCII 批处理） |

---

## 两套 Agent 怎么隔离

| 维度 | Agent 1（quant） | Agent 3（writing） |
|---|---|---|
| DSH profile | `~/.dsh/profiles/quant` | `~/.dsh/profiles/writing` |
| 工作区 | `C:\AI_workspace\stock_agent_manager` | `C:\AI_workspace\wechat_writing` |
| MCP 服务端 | `srq`（11 个工具，含 4 个模拟下单） | `draft`（3 个工具） |
| shell / subagent / workflow / web | 全部关闭 | 全部关闭 |
| 实测工具数 | 20 | 12 |
| 系统提示词 | `cordis/prompts/agent1.md` | `cordis/prompts/agent3.md`（人设 + 文风 + 固定免责声明） |
| 发布能力 | —— | 不存在 |

两个 profile 的 patch 由 `tools/build_cordis.py` 从同一份提示词生成，避免手改漂移。
实测证据：quant 会话真实发出 `mcp__srq__run_research_instruction` 并复述实验 ID；
writing 会话回答 `NO_SRQ_TOOL`，但能调 `mcp__draft__wechat_probe_draft`。

---

## 与项目简报的偏差（重要）

五处与简报假设不一致，均已按实际调整，细节见 [docs/architecture.md](docs/architecture.md) 第 5 节：

1. **`srq` / SolidRockQuant 不存在**（机器上没有，PyPI 也不可达）→ 按约定工具面自建
   `srq-compat` MCP 服务端，命令仍是 `srq mcp serve`，工具名与简报一致。它**不是** SolidRockQuant，
   接真机时字段需要逐项核对。
2. **`deepseek-harness-sdk` 不存在**（PyPI 无此包，外网仅 DeepSeek API 可达）→ 控制平面改用
   `dsh` CLI + `agents/mcp_client.py`；Python 侧零第三方依赖，因此不存在 3.12 兼容性问题。
3. **数据是合成样本**（无行情源）→ 40 个标的、六年、约 6.2 万条日频记录，固定种子生成，
   sha256 固定。它的用途是验证链路，**不能**用于推断真实市场。
4. **`dsh headless` 不消费 agent preset**（源码硬限制）→ Phase 1 用 profile 级隔离；
   preset 形态的配置保留给 Web 会话，未在 Web 上实测。
5. **`factor_logic` 由代码映射，不由模型选择** → 否则模型就决定了回测跑什么。

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

## Phase 2/3 预留（本期不实现）

- Router：`agents/envelope.py` 已定义统一信封（`schema/agent/kind/status/id/artifacts/compliance`），
  派活规则应在代码里按 `kind + status + handoff_eligible` 硬编码，不交给模型判断。
- 数据接入：已经落地为「CSV 快照」路线——`quant/providers/csv_import.py` 导 v2，
  `load_panel` 消费，`NFR_DATA_DIR` 切换。工具面不变，引擎不变。
- 部署验证：`run_paper_session` 已能产出模拟台账，接真实行情后可直接复用。
- 未做：常驻调度、自主派活、实盘、自动发布、Agent 4。
