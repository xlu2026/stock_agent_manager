# QMT 策略部署（2026-11-28）

> **当前状态：执行近似版已冻结。** 版本 sha `089dfd...`，跟踪误差 4.22%；
> 决策与残余误差见 `docs/qmt-alignment-decision.md`。不再追两阶段逐日复现。
> 前向模拟盘见 `docs/paper-tracking.md`（paper 版 sha `9766768f...`）。

## 1. 做到哪一步

| 能力 | 状态 |
|---|---|
| 把 Spec 渲染成 QMT 内置 Python 策略 | ✅ |
| 写入仓库 `output/qmt/` | ✅ |
| 复制到 QMT 的 `python\` 目录 | ✅（只复制文件；**不会自动注册策略**） |
| 生成审计 JSON（spec/assets/sha256） | ✅ |
| 生成可直接导入的 `.rzrk` | ❌ `.rzrk` 是 QMT 加密导出格式，外部无法生成 |
| QMT 客户端内注册/启动策略 | ❌ 无公开 API，仍需人工新建/粘贴/启动 |
| 通过 `xtquant` 外部下单 | ❌ 无包、miniQMT 权限被拒 |
| 自动部署 + 自动运行 | ❌ 当前不可行 |

**边界：本仓库只生成/复制文件，不启动策略、不连接交易接口、不下单。**

## 2. 已生成的策略

| 项 | 值 |
|---|---|
| Spec | 动量+低波 50/50，`weighting=inverse_vol`，top_k=8，月度 |
| 仓库文件 | `output/qmt/nfr_mom_lowvol.py` |
| 审计 | `output/qmt/nfr_mom_lowvol.py.json` |
| QMT 侧 | `C:\AI_workspace\_tools\中泰qmt信创模拟交易端\python\nfr_mom_lowvol.py` |
| sha256 | `089dfd831e150da72552ef3d1315863a42aba95244dc91b5a7f173f8a22b5cc1` |
| 账户配置 | `config/qmt.json`（gitignored） |

账户号不再写死在每个策略里：生成器默认读 `config/qmt.json`，
生成文件启动时也优先读它；读不到才用文件里的 fallback。
不要把这个文件直接当自动交易策略运行。

## 3. 用法

```powershell
python scripts\deploy_qmt.py `
  --spec output\qmt\spec_mom_lowvol_invvol.json `
  --snapshot C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125 `
  --name nfr_mom_lowvol
```

账户号和 QMT 目录默认从 `config/qmt.json` 读取；仍可用 `--account` / `--qmt-dir` 覆盖。
`--dry-run` 只看源码不写盘；`--force` 才允许覆盖同名文件；`--no-qmt-copy` 只写 `output/qmt`。

### 3.1 账户配置

`config/qmt.json`：

```json
{
  "account_id": "YOUR_ACCOUNT_ID",
  "qmt_python_dir": "C:\\AI_workspace\\_tools\\中泰qmt信创模拟交易端\\python"
}
```

- 已在 `.gitignore`，不会入库；
- 生成文件会嵌入配置路径，启动时 `_load_account()` 优先读配置；
- QMT 若禁止本地文件读取，会退回生成文件里的 fallback 账号，此时改配置后要重新生成；
- 改账户只改这一处，不要逐个改 Python。

## 4. 人工步骤（重要：不要用“导入公式”）

QMT 的“导入公式”只接受 `.rzrk`，而 `.rzrk` 是 QMT 自己导出的**加密**策略文件，
外部无法生成。生成的 `.py` 要走“新建 Python 策略”：

1. 打开 QMT 客户端 → 模型研究/我的策略 → **新建 Python 策略**；
2. 用编辑器打开 `output/qmt/nfr_mom_lowvol.py`（GBK），全选复制，粘贴到 QMT 策略编辑器；
3. 编译；账户号来自 `config/qmt.json`，不需要在代码里改；
4. 先在**模拟盘**跑一轮，核对下单方向/数量/价格；
5. 确认后手工启动策略。

如果以后需要 `.rzrk`：在 QMT 里保存/编译该策略后，右键策略 → 导出，QMT 会生成 `.rzrk`；
之后换机器时再用“导入公式”导入。仓库不生成 `.rzrk`。

## 5. 支持范围

- `single_factor`：`momentum_12_1`、`low_vol_60d`；
- `momentum_param`：lookback/skip；
- `composite`：上述价格因子的 z-score 加权；
- `weighting`：`equal` / `score` / `inverse_vol`。

不支持（渲染时直接报错，不生成跑不通的代码）：

- `value_proxy` / `quality_proxy`：QMT 财务数据接口未验证；
- `vol_target`：QMT 内现金管理/缩放逻辑未实现；
- `vol_target` 之外的组合中性化：缺少行业/市值数据。

## 6. 已知限制

- `.rzrk` 是 QMT 加密导出格式，不能由仓库生成；“导入公式”只能导入 QMT 自己导出的 `.rzrk`；
- 复制 `.py` 到 QMT 目录不会自动注册；必须新建 Python 策略并粘贴；
- QMT 策略只能用客户端内的 `ContextInfo`/`order_shares`，不是外部 `xttrader`；
- 生成策略按收盘价 `fix` 下单、按 100 股取整，没有滑点/容量/涨跌停校验；
- 参数/股票池写在生成文件里，改策略要重新生成，不要手改生成文件；
- 未在真实 QMT 中执行过，只通过 Python 语法/单测验证。

## 7. 2026-11-28 回测截图分析

第一次截图（旧代码）：单位净值 1.301、基准 1.559，年化 8.7% vs 11.6%，阿尔法 -1.6%，
**跑输基准**。

第二次截图（10:24）：单位净值 1.443、基准 1.559，年化 9.9% vs 11.6%，阿尔法 +0.6%，
贝塔 0.741，夏普 0.770，胜率 66.2%，平仓/开仓 74/104。**仍然跑输基准**。

但两次日志都显示 2020 年选出了 `601136/601868/688472` 等当时未上市的代码；
说明 QMT 里运行的仍是**没有上市日期过滤**的版本，结果不能作为策略结论。

生成器已加 `ASSET_FIRST`（从快照 prices 取每个标的第一条行情日期）：
当前日期早于首个行情日直接跳过。新文件 sha 见上表；请确认 QMT 编辑器里能搜到
`ASSET_FIRST`，再重跑。

进一步对齐（2026-11-28）：

- `UNIVERSE_CHANGES`：从 `universe.csv` 压缩成 13 个成分生效版本，按日期过滤；
- `REBALANCE_DATES`：71 个月末交易日，与引擎 `n_rebalances=71` 对齐；
- `inverse_vol` 补了单票 25% 上限；
- 信号用前一日，成交用当日；
- 采用手工 `_equity` + `order_shares`（sha `089dfd...`）：按当前总资产/持仓市值算目标仓位，
  这是目前 QMT 回测里最接近引擎的版本；
- `order_target_percent` 版本（sha `a2f42c...`）实测更差：QMT 同 bar 卖出回款不变成可用资金，
  会报“可用资金不足”并跳单，已回退，不再使用；
- 生成文件 sha 见上表。

**基准**：QMT 回测设置只能选 000300，不能直接设成引擎的 40 只等权基准。
不要把 QMT 的“基准/阿尔法”当作策略超额；对齐时只比较策略 NAV，
等权基准用同一份数据单独算。若一定要 QMT 内比基准，需要把引擎基准也改成 HS300
（当前快照没有指数序列，未实现）。

## 3.2 日频 NAV 导出与对账

生成策略会在回测时写：

```
output/qmt/nfr_mom_lowvol_nav.csv   # date,net_value
```

如果 QMT 禁止本地写文件，策略日志会打印 `NAV export failed`，这时只能手工从
QMT 结果页导出净值和引擎对比。

对账：

```powershell
python scripts\compare_qmt_nav.py `
  --qmt output\qmt\nfr_mom_lowvol_nav.csv `
  --experiment exp-002c539a8e70 `
  --out output\reports\qmt_nav_compare.json
```

输出：共同天数、累计收益、日收益相关性、跟踪误差、最大单日差、最终净值差。

## 3.3 同一份 QMT 数据回灌引擎

生成“只导出日线、不交易”的策略：

```powershell
python scripts\deploy_qmt.py --spec output\qmt\spec_mom_lowvol_invvol.json `
  --snapshot C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125 `
  --name nfr_mom_lowvol --export-bars
```

它会生成并复制 `nfr_bars_export.py`；在 QMT 跑 2021-2026 后得到
`output/qmt/qmt_bars.csv`。然后：

```powershell
python scripts\import_qmt_bars.py `
  --bars output\qmt\qmt_bars.csv `
  --base-snapshot C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125 `
  --out C:\AI_workspace\smartx_client\out\real40_qmt_20261128
```

再用 Agent 1 在这个 QMT 数据快照上跑同一 spec，比较两边 NAV。
注意 `import_qmt_bars` 的 OHLC 全部用 close 近似，只适合价格因子对齐。

区间/基准/QMT 数据与引擎研究不一致，也不能直接和引擎的 2021-2026 结果对比。
详见 `output/reports/qmt_backtest_analysis.md`。

## 8. Agent 4

本轮没有创建 Agent 4。部署本质是“代码生成 + 文件投递 + 人工导入”，
确定性 CLI 比 LLM 更安全；等 QMT 策略注册/启动有公开接口，再考虑 Agent 4。
