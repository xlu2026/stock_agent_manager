# 三个优化点的可行性、优先级与方案（2026-11-25）

> ## 2026-11-28 复审后的执行计划
>
> 详细复盘见 `docs/review-2026-11-28.md`。原则：先补口径和账本，再扩策略/数据。
>
> | 优先级 | 任务 | 状态 | 产出 |
> |---|---|---|---|
> | P0 | 固定基准/指标/成本口径 | ✅ | `docs/metrics-and-benchmarks.md` |
> | P0 | 研究流程 playbook | ✅ | `docs/research-playbook.md` |
> | P0 | 预注册模板 | ✅ | `templates/pre_registration.md` |
> | P0 | 关键试验账本 | ✅ | `docs/experiment-ledger.md` |
> | P1 | 数据刷新/体检/双源 runbook | ✅ | `docs/data-runbook.md` |
> | P1 | 执行/paper runbook | ✅ | `docs/execution-runbook.md` |
> | P1 | paper 日报/异常模板 | ✅ | `templates/paper_daily.md`、`templates/incident.md` |
> | P1 | 固定候选成本敏感性 | ✅ | `output/reports/cost_sensitivity.md` |
> | P1 | paper 订单级对账 | 待启动 | 12-01 起 |
> | P2 | 财报 PIT / 历史成分 / 扩池 | 暂缓 | 需外部数据源 |
> | P2 | Agent 4 / QMT 自动启动 | 不做 | 无公开 API |
>
> 本轮不做：实盘、自动登录、两阶段调仓、为扩池而扩池。

结论先行：

| 优化点 | 可行性 | 优先级 | 依赖 |
|---|---|---|---|
| 1. 第二数据源 + 交叉验证 | 高 | **P1（基础版已完成 2026-11-25）** | SmartX Python 已带 akshare/tushare；先做 AkShare |
| 2. 策略多重性与参数解耦 | 高，但必须重构 | **P0（已完成 2026-11-25）** | 现有 `Spec`/`engine`/`instruction`/MCP 都是单因子硬编码 |
| 3. 策略部署到 QMT | 部分可行；全自动不可行 | **P2（文件生成/投递已完成 2026-11-28）** | miniQMT 政策不能开、无 `xtquant`、策略注册无公开 API |

建议顺序：**先 2，再 1，最后 3**。策略抽象是所有后续工作的地基；数据源是风险对冲；QMT 部署当前被权限和接口卡住。

> **P0 已完成（2026-11-25）**：`quant/strategies/` 注册表、`Spec.strategy + params`、
> 引擎 dispatch、参数 schema 校验、MCP schema 枚举；旧 `factor` 路径的
> `nav_hash=fc5c9e...` 逐位未变。新增 `momentum_param`、`composite` 两个实验策略。
> 后续也已完成：四字段指令支持显式 `strategy/params`；Agent 1 信封/实验索引记录策略；
> 因子分析支持任意策略打分。230+ 项单测、14 项验收全绿。

> **2026-11-26 完成情况（第 1、2 点收尾）**
>
> 第 1 点已完成：`quant/providers/sources.py` 注册表；AkShare 价格改为“不复权 + 官方涨跌幅”
> 连续价（`002085` 异常消失）；导出每股净资产/TTM EPS（公告日=法定截止日）；覆盖率分母改为
> 时点成分有效期；`compare_snapshots --update-manifest` 写 crosscheck；`compare_constituents.py`
> 做最新成分核对。剩余：38/40 只（000961/600068 拉取失败）、AkShare 无历史 PIT 成分、
> 两边财报口径差异大暂不能互验、`dv` 仍只 hash 价格。
>
> 第 2 点已完成：`quant/portfolio.py` 组合构造器（equal/score/inverse_vol/vol_target）；
> composite 支持 `normalize=rank`、`winsorize`、`neutralize=demean`；策略声明 `required_data`
> 并在引擎/校验中拦截；因子分析输出逐因子 `component_ic`；`quant/sweeps.py` 网格 + BH 多重检验；
> `scripts/compare_experiments.py` 自动对照。剩余：行业/市值中性化缺少快照字段，暂不实现。
>
> 第 3 点未动：miniQMT 政策/xtquant 限制仍在。

---

## 1. 第二数据源 + 交叉验证

### 现状

- 只有一个数据来源：`scripts/export_baostock_snapshot.py` → `csv_import` → v2 快照；
- 消费端 `quant/data.py::load_panel` 只认一个 `NFR_DATA_DIR`；
- 已有 `quant/providers/base.py::Provider` 协议（`fetch(start,end,universe) -> Snapshot`），
  也有 `qmt.py` 骨架，但 baostock 脚本没走这个协议，**没有数据源注册表**；
- 2026-11-12 已经遇到一次 baostock 登录超时，单源风险是真实的。

### 可行性

高。实测 **SmartX 自带的 Python 3.9 已安装** `akshare`、`tushare`、`pandas`、`requests`；
仓库 Python 3.12 没有（保持标准库）。所以第二数据源可以沿用现有模式：
**用 SmartX Python 跑导出脚本，仓库只消费 CSV**。

推荐第二源：

- **AkShare**：免费、无需 token、覆盖 A 股日线/指数成分/财务，最适合做交叉验证；
- Tushare 作为可选第三源（需要 token/积分，不作为默认）。

不建议把 QMT 作为第二源：外部读不到（无 `xtquant`），只能人工导出。

### 需要补的抽象

1. `quant/providers/sources.py`：数据源注册表 `{name: Provider}`，统一 `fetch + write_snapshot`；
2. `quant/providers/akshare.py`：实现 `Provider`，映射到 v2 契约（价格/复权/财报公告日/成分）；
3. `scripts/export_akshare_snapshot.py`：CLI，参数与 baostock 脚本对齐；
4. `scripts/compare_snapshots.py`：**数据 diff**，不是因子收益 diff。比较重叠日期/标的：
   - close 相对差、复权因子、成交量缺失、财报公告日；
   - 输出差异报告与阈值告警；
5. manifest 增加 `source`、`crosscheck`（对比源、重叠天数、最大差异、结论）；
6. Agent 2 的 `refresh_snapshot` 增加 `source` 参数（baostock / akshare），默认 baostock。

### 优先级与工作量

**P1**，约 3–5 天：AkShare 适配 2–3 天、diff 1 天、测试/文档 1 天。
先做“日线 + 成分 + 财报”三张表的重叠校验；不急着全量切换主源。

> **P1 基础版已完成（2026-11-25）**：`quant/providers/akshare.py`、
> `scripts/export_akshare_snapshot.py`、`scripts/compare_snapshots.py`；
> Agent 2 的 `refresh_snapshot` 已加 `source=baostock|akshare`（akshare 需 base_dir）。
> 交叉验证发现并修复了 baostock hfq 在除权日的假跳空：新增 `--continuous`
> （不复权 OHLC + preclose 链式总收益价），修复后 600655 异常消失，max 收益差 8.856%→2.946%，
> 剩余异常集中在 002085（AkShare hfq 与 baostock 不一致）。详见 `docs/data-sources.md`。
> 2026-11-26 已在正式连续价快照 `dv-036ee34e7f93`（重算前版本；全文件版本为 `dv-91efdffbf9fe`）上重跑两条真实动量实验：
> CAGR 差异约 -0.02pp，方向不变；对照见 `output/reports/core_rerun_comparison.md`。
> 2026-11-26 多因子/参数化网格：低波/价值组合四个区间优于单因子动量，
> 短周期动量更差；详见 `output/reports/strategy_grid_comparison.md`。

风险：AkShare 接口/字段会变、限频；需要锁定版本、缓存原始 CSV、失败不落半份快照。

---

## 2. 策略多重性与参数解耦

### 现状：没有为多策略预留

- `Spec.factor` 是**单个字符串**，`FACTORS` 只有 4 个固定因子；
- `engine.run_backtest` 硬编码“单因子排名 → 取 top_k → 等权”；
- 因子预热 `MIN_HISTORY`、函数表 `FACTOR_FUNCS`、`spec.FACTORS` 三处登记；
- `instruction.py` 用关键词表映射到单个因子；
- MCP 的 `SPEC_SCHEMA.factor` 枚举、研究工具 schema 都硬编码单因子；
- 参数（动量 252/21、低波 60）写死在因子函数里，无法按实验改；
- 新增一个策略要同时改：spec、factors、engine、instruction、MCP schema、测试，容易漏。

结论：**当前架构不适合“多策略 + 参数扫描”**，这是 P0 级结构问题。

### 目标设计

1. **策略注册表** `quant/strategies/`：

```python
class Strategy(Protocol):
    id: str
    version: str
    params_schema: dict          # JSON Schema：类型/范围/默认值
    required_data: tuple[str, ...]  # price / fundamentals / universe
    def warmup(self, params: dict) -> int: ...
    def score(self, panel, i, params) -> dict[str, float]: ...
    def construct(self, scores, params) -> dict[str, float]: ...
```

2. **Spec 改为 `strategy` + `params`**，保留兼容层：

```json
{"strategy": "single_factor", "params": {"factor": "momentum_12_1", "lookback": 252, "skip": 21}, ...}
```

- 旧 `factor` 字段自动映射成 `single_factor` + `params.factor`；
- 旧实验的 `canonical()` 和 `nav_hash` 必须逐位不变（回归锚）；
- `strategy_version` 进入指纹，策略代码改动不会悄悄复用旧实验 ID。

3. **组合构造器独立**：`top_k_equal` 先实现，后续 `score_weighted`、`vol_target`、
   `industry_neutral` 作为独立构造器，不塞进策略。

4. **参数校验**：每个策略一份 JSON Schema/dataclass；未知参数、越界、类型错误直接拒绝；
   `params` 进入实验记录和指纹。

5. **instruction / MCP 从注册表生成**：关键词映射到 `strategy_id`，schema 枚举不再手写；
   研究模式仍不让模型自选因子/参数。

### 迁移步骤（保持基线不变）

1. 抽 `Strategy` 接口 + `single_factor` 适配器，engine 改为 `score → construct`；
2. 跑全量回归：合成样本动量实验的 `nav_hash` 必须等于 `fc5c9e...`；
3. 把 4 个因子注册成 4 个策略（或 1 个参数化 single_factor + 4 个 factor）；
4. 加 1 个多因子策略（如动量+低波）和 1 个参数化动量（lookback/skip 可调）；
5. 更新 instruction/MCP schema、Agent 1 提示词、验收；
6. 最后再考虑参数扫描（grid/optuna 不做，先做显式参数）。

### 优先级与工作量

**P0**，约 1–2 周。它是“测更多策略、改参数”的前置条件；不做的话，每加一个策略都是复制粘贴 + 改 5 处。

---

## 3. 部署策略到 QMT

### 事实

- 本机 QMT 完整客户端能登录（2026-11-13 20:51 登录成功），能跑**内置 Python 策略**；
- `XtMiniQmt.exe` 的登录被拒：`status 23，请联系券商开通对应权限`；miniQMT 已明确政策不能开；
- 没有 `xtquant` 包（仓库 Python / SmartX Python 都 import 失败），外部 `xtdata`/`xttrader` 不可用；
- QMT 策略文件在安装目录 `python\`（示例 `.py`），但策略的注册、自动运行由客户端内部
  `FormulaConfig` 管理（日志 `FormulaConfig::initIndexMap`），**没有公开的注册/启动 API**；
- 跨券商：QMT 策略 API（`ContextInfo`、`order_shares`、`get_market_data`）是迅投标准，
  代码可复用；但每家券商的客户端版本、登录权限、数据、自动运行配置不同，部署仍需适配。

### 可行范围

| 能力 | 可行性 |
|---|---|
| 生成 QMT 内置策略 `.py`（用 `ContextInfo`/`order_shares`） | ✅ 高 |
| 把 `.py` 放到 QMT `python\` 目录 | ✅ 文件操作 |
| 让 QMT 自动注册/启动/停止策略 | ❌ 无公开 API，需人工在客户端导入/启动/设自动运行 |
| 外部监控策略状态/持仓 | ⚠️ 只能读 QMT 导出/日志，不是实时 API |
| 通过 `xtquant` 外部下单 | ❌ 无包 + miniQMT 权限被拒 |

结论：**“生成 + 投递 + 人工导入”可行；“自动部署并自动运行”当前不可行。**
不建议为了自动部署去逆向客户端 DB 或注入进程。

### Agent 方案评估

| 方案 | 评价 |
|---|---|
| 扩展 Agent 1 | ❌ 不推荐。Agent 1 是研究/回测工具面，加入部署会拿到文件写/进程/账户权限，违反最小权限；研究结论与执行混在一起 |
| 新增 Agent 4（执行/部署） | ✅ 推荐（如果一定要 agent）。只挂部署工具：渲染策略、检查环境、投递文件、读日志/状态；没有回测/研究工具 |
| 纯确定性 deployer + CLI | ✅ 最稳。部署本质是代码生成 + 文件投递 + 人工步骤，LLM 只做编排；可先做 `quant/deploy/qmt.py`，再决定是否包 Agent 4 |

优先级：**P2，部分完成**。文件生成/投递已做（`quant/deploy/qmt.py`、`scripts/deploy_qmt.py`），
QMT 内注册/启动仍需人工；miniQMT 封死、无 xtquant，自动部署不做。

如果先做原型，范围建议：

1. `quant/deploy/qmt.py::render_qmt_strategy(spec, params)`：生成只依赖 `ContextInfo` 的标准策略；
2. 模板包含：取数、调仓日判断、`order_shares`、日志/CSV 落盘；
3. `scripts/stage_qmt_strategy.py`：写到 QMT `python\`，打印“请在客户端导入/启动”；
4. 不做自动启动、不做账户下单。

---

## 4. 建议路线图

1. **P0（已完成）**：策略注册表 + `Spec.strategy/params` + engine 解耦；基线 nav_hash 不变。
2. **P1（基础版 + 收尾已完成，数据仍有 2 只缺口）**：AkShare 第二源、交叉验证、财报、连续价。
3. **P2（暂缓）**：QMT 策略生成/投递原型；miniQMT 权限明确不可开后，不投入自动部署。
4. **Agent 侧**：Agent 1 保持研究；Agent 2 保持数据；未来新增 **Agent 4（执行/部署）**，
   而不是把部署塞进 Agent 1。
