# 交接文档（Handoff）

> 给下一个会话的 agent 看的第一份文件。读完这一页，你应该知道：项目在哪一步、
> 什么不能碰、下一步做什么、以及哪些坑别人已经踩过。
>
> 最后更新：2026-11-09 ｜ 对应状态：Phase 1 完成；数据接入改为「CSV 快照」路线
> （QMT 数据下载受政策限制，见第 7 节）

---

## 1. 三十秒版本

这是一个个人项目：**用 AI 把投资判断写成可回测因子，并公开记录过程**。
Phase 1 已经跑通"研究指令 → 确定性回测 → 指标与实验 ID"，以及公众号文章草稿链路。
**下一步是接真实行情**：v2 契约的消费端和通用 CSV 导入器已经就位，缺的只是
一份真实日线 CSV。券商 QMT 的数据下载被政策限制，但行情来源与交易通道已经解耦，
换成任何能导出 CSV 的数据源都不需要改引擎（见第 7 节）。

当前规模：**110 项单测、11 项验收、MCP 11 个工具**，全绿。

---

## 2. 先读什么

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `AGENTS.md` | 行为边界（一票否决项），每个会话自动注入 |
| 2 | 本文件 | 当前状态与待办 |
| 3 | `docs/architecture.md` | 分层、工具面、券商层、数据接入（第 9 节） |
| 4 | `docs/strategy.md` | 策略规格、参数口径、加因子 checklist |
| 5 | `README.md` | 快速开始 |

公众号账号状态（接口权限、白名单、变现）在 `docs/wechat-account.md`，与本仓库开发解耦。
公众号之外的平台矩阵、知乎导出与发布记录在 `docs/platforms.md`。

---

## 3. 已完成

| 模块 | 位置 | 状态 |
|---|---|---|
| 确定回测引擎（4 因子、成本、基准、指标、IC） | `quant/engine.py` `quant/factors.py` | ✅ 可复现（`nav_hash`） |
| 四字段研究指令契约（自然语言 → 因子） | `quant/instruction.py` | ✅ 模型不能自选因子 |
| MCP 服务端 | `quant/mcp_server.py` | ✅ 11 个工具 |
| 实验登记簿 | `quant/experiments.py` `experiments/` | ✅ |
| 模拟盘 + 券商抽象层 | `quant/paper.py` `quant/broker/` | ✅ 只有 PaperBroker |
| 下单三段式（提案 → 人工批准 → 提交） | `quant/broker/proposals.py` `approve.py` | ✅ 已实测 |
| 写作侧（渲染、合规、草稿接口） | `writing/` | ✅ |
| 知乎导出（HTML/MD/meta，无发布） | `writing/platforms/zhihu.py` `writing/export.py` | ✅ 导出 + 人工清单 |
| 知乎发布（开篇） | https://zhuanlan.zhihu.com/p/2103182137985976284 | ✅ 2026-11-09 手动发布；AI 声明/首发句/3 话题已核对 |
| DSH 两套 profile（工具面隔离） | `cordis/` + `tools/build_cordis.py` | ✅ 已实测 |
| 数据契约 v2 + 快照体检 + 通用 CSV 导入器 | `quant/providers/` | ✅ 消费端已认 v2，无真实数据 |
| QMT 只读导出 sidecar（不下载） | `scripts/export_qmt_snapshot.py` | ✅ 骨架 + 假 xtquant 单测，未接真终端 |
| 策略规格文档 | `docs/strategy.md` | ✅ v1.0 |

---

## 4. 未完成 / 下一步

按优先级：

| # | 任务 | 阻塞点 |
|---|---|---|
| 1 | 在 QMT 机器上跑 `export_qmt_snapshot.py --probe`，确认本地数据范围与字段 | 只差一次实跑；不需要下载权限 |
| 2 | 跑正式导出，得到第一份真实快照，再用 `doctor` 核对 | 同第 1 步；数据源已确定 |
| 3 | 实测 `xttrader` 下单通道 + 程序化交易报备 | 第 3 问未验证；接 Phase 2 前必须做 |
| 4 | 组合构建层（多因子、权重、敞口上限） | 未开始 |
| 5 | 公众号：原创声明 + 赞赏 | 需用户在后台手动勾（OpenAPI 无此字段） |

**推荐从第 1 步开始**：先探再导，避免一次拉全市场把问题埋进数据里。
`--probe` 不写任何文件，只报告本地能读到多少行、哪些标的是空的。

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
| `dsh headless` 用不了 preset | 源码硬限制（headless 不消费 preset） | 用 profile 级隔离 |
| 微信错误被判成"成功" | HTTP 200 + body 里带 errcode | `probe_draft_api` 已按 errcode 分类，别再改回去 |
| 沙箱里跑测试全红 `PermissionError` | Python 3.12 的 `tempfile.mkdtemp` 在 Windows 建出仅所有者可访问的目录，沙箱令牌进不去；与代码无关 | 用完整权限（full access）跑，或在用户自己的终端里跑；不要为此改测试 |

验证命令（改完必须跑）：

```powershell
python -m unittest discover -s tests -t .
python scripts\acceptance.py
```

---

## 7. 待决策：数据源（QMT 数据下载已被限制）

**已知事实**（2026-11-09）：

- 中泰客服："政策原因，QMT 不支持下载数据"。
- 社区记录（<https://www.jisilu.cn/question/526075>）：QMT 自 2026-10-23 起限制
  **读写本地文件、与外部网站交互、在服务器上运行**，但**程序化下单不受影响**。
- 用户实测/确认：**终端里已下载的数据能读**（第 2 问）、**能导出本地文件**（第 4 问）；
  `xttrader` 大概率可用（第 3 问未验证）。关闭的是"下载"这一类功能，不是全部接口。

**所以现在走这条路**：数据侧只读，交易侧待验证。

| 问题 | 状态 | 结论 |
|---|---|---|
| 1. 被关的是下载还是全部 | 已知 | 关闭"下载"；已在终端里的数据仍可用 |
| 2. 已下载数据能否读本地缓存 | ✅ 能 | `QmtProvider.fetch` 走这条路，不下载 |
| 3. `xttrader` 下单是否照常 | ❓ 大概率能 | 接 Phase 2 前必须实测，并做程序化交易报备 |
| 4. 能否导出成本地文件 | ✅ 能 | `scripts/export_qmt_snapshot.py` 已就位 |

**当前做法**：终端里人工补数据 → `scripts/export_qmt_snapshot.py` 只读导出 v2 快照
（**从不调用 `download_history_data`**，测试里用假 xtquant 钉住了这条性质）。

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

**结论**：原来的"导出是分水岭"已经不成立——本地快照 + sha256 复现的架构不依赖券商，
只读导出这条最省事的路已经打通。见 `docs/architecture.md` 9.5。

---

## 8. 关键 ID（运维用，勿丢）

| 项 | 值 |
|---|---|
| 基准实验（动量，top_k=8） | `exp-a359c2d77697` |
| 基准 `nav_hash` | `fc5c9e778707e5f1280d1084c4018342aa4013a248e9aec2b3b2391b64a47f1a` |
| 数据快照版本 | `dv-572bafec2a92`（40 标的 × 1565 交易日，sha256 固定） |
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

然后读 `docs/architecture.md` 第 9 节。v2 消费端已经做完，下一步不是改代码，
而是拿一份真实 CSV 走一遍：

```powershell
python -m quant.providers.csv_import --prices raw\prices.csv --out snapshots\first ^
    --universe <池名> --source "<来源>" --adjust-mode backward
$env:NFR_DATA_DIR = "snapshots\first"
python -m quant.cli doctor
```

先把 `doctor` 里的 `filled_rows` / `point_in_time_universe` / `source` 看一遍，
再决定这份数据敢不敢用来下结论。不要重新设计架构——现有分层是有理由的，改动前先看第 5 节。

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
