# 数据源与交叉验证（P1）

## 1. 现状

| 角色 | 来源 | 入口 | 状态 |
|---|---|---|---|
| 主源 | baostock | `scripts/export_baostock_snapshot.py` | ✅ 已有真实快照 |
| 第二源 | AkShare | `scripts/export_akshare_snapshot.py` | ✅ 2026-11-25 接入 |
| 第三源（暂不可用） | QMT | `quant/providers/qmt.py` 骨架 | ❌ 无 `xtquant` / miniQMT 权限 |

AkShare 只在 **SmartX 自带的 Python 3.9** 里可用（本机实测 `akshare 1.18.88`）；
仓库本身仍只依赖标准库。不要把 akshare 加进仓库运行依赖。

## 2. 导出 AkShare 快照

推荐复用主源的标的/日历/时点成分，只换价格来源：

```powershell
$py = "C:\Users\<you>\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
& $py -u scripts\export_akshare_snapshot.py `
  --base-snapshot C:\AI_workspace\smartx_client\out\real40_pit `
  --out C:\AI_workspace\smartx_client\out\real40_pit_akshare `
  --min-coverage 0.8 --retries 2 --delay 0.5
```

- 价格用 `adjust="hfq"`（后复权），与 baostock `adjustflag=1` 语义对齐；
- 东财 `stock_zh_a_hist` 失败时自动回退 Sina `stock_zh_a_daily`；
- 覆盖率低于 `--min-coverage` 的标的剔除，并写进 `manifest.notes.warnings`；
- 复用 base 的 `calendar.csv` / `universe.csv`，所以 `universe_point_in_time=true`；
- 目前**不导出财报**，交叉验证只覆盖价格。

## 3. 交叉验证

```powershell
python scripts\compare_snapshots.py `
  --a C:\AI_workspace\smartx_client\out\real40_pit `
  --b C:\AI_workspace\smartx_client\out\real40_pit_akshare `
  --out output\reports\crosscheck_real40.json
```

比较内容：

- 重叠标的/日期；
- 价格比（中位数、变异系数）——识别复权基准差异；
- **日收益差**（max / p95）——复权基准无关，是真正的数据一致性指标；
- 缺失行（只统计共同标的，避免把“被剔除的标的”算成缺失）；
- 时点成分差异；
- top 10 收益差异常点。

判定：

- `ok`：最大收益差 ≤ `--max-return-diff`（默认 0.002）；
- `warn_outliers`：p95 达标，但存在少数异常点；
- `warn`：p95 也超标；
- `fail`：没有重叠数据。

## 4. 2026-11-25 实测结果（baostock vs AkShare）

| 指标 | 值 |
|---|---|
| 共同标的 | 30 / 40（10 只因拉取失败/覆盖率不足被剔除） |
| 共同日期 | 1,456（2019-01-02..2024-12-31） |
| 共同行数 | 43,680 vs 43,628 |
| 缺失行 | 52（仅共同标的） |
| 日收益差 p95 | **0.1525%** |
| 日收益差 max | **8.856%** |
| 判定 | `warn_outliers` |

结论：**绝大多数日收益一致（p95 约 0.15%），但存在少数异常点，不能直接切换主源。**

### 4.1 `600655.SH`：主源快照的除权日假跳空（已定位并修复）

`600655.SH` 2020-11-25 的 -11.69% 不是 AkShare 错，而是 **baostock 的 hfq 收盘价在除权日不连续**：

- 2020-11-24 收盘 1919.06；
- 2020-11-25 的除权参考价（preclose）是 1744.15，收盘 1694.64；
- 正确的当日收益 = 1694.64 / 1744.15 - 1 = **-2.84%**；
- 快照只存 close，引擎用“前一日 close”算收益，得到 1694.64 / 1919.06 - 1 = **-11.69%**，多跌了 8.8%。

**修复**：导出时增加 `--continuous`，用不复权 OHLC + `preclose` 链式生成连续总收益价：

```powershell
$py = "C:\Users\<you>\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
& $py -u scripts\export_baostock_snapshot.py `
  --out C:\AI_workspace\smartx_client\out\real40_pit_cont1 `
  --stocks sh.600655,sh.600000,... --start 2019-01-02 --end 2024-12-31 `
  --continuous --min-coverage 0
```

修复后 `600655` 的连续价 9.7942 → 9.5162 = **-2.84%**，假跳空消失。
注意：`--continuous` 暂不支持增量，走全量重建；重建出的快照目前没有 fundamentals。

### 4.2 `002085.SZ`：改用“不复权 + 官方涨跌幅”后消失

`002085.SZ` 之前 baostock 约 `+10%`、AkShare hfq 约 `+7.5%`。把 AkShare 适配器改成
**不复权 OHLC + 官方 `涨跌幅` 链式总收益价**后，2021-2026 的 38 只共同标的里
`002085` 不再出现在异常列表，说明差异来自 hfq 调整路径，不是原始行情。

剩余异常是 `601868.SH`，因为它走了 Sina 回退源（没有 `涨跌幅`，只能按收盘价链式），
除权日会有 0.1–0.5% 的误差；这是回退源的已知限制。

### 4.3 正式连续价快照（2026-11-25）

用 `scripts/rebuild_continuous_snapshot.py` 在现有 PIT 快照上**只重建价格**，保留 40 只标的、
1905 个交易日、时点成分和 fundamentals：

| 项 | 值 |
|---|---|
| 目录 | `C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125` |
| data_version（全文件 hash） | **`dv-91efdffbf9fe`** |
| 旧 prices-only 版本 | `dv-036ee34e7f93`（同一目录重算前） |
| 标的 / 交易日 | 40 / 1,905 |
| 行数 | 70,931 |
| 体检 | `ok`（含 `universe.coverage`、`prices.coverage`） |
| 最新指针 | `output/data/latest.json` 已指向该目录 |

Agent 1 用 `--latest` 跑了一次冒烟回测：

```
experiment_id = exp-80bb01c3a9be
data_version  = dv-036ee34e7f93  # 重算前；当前全文件版本 dv-91efdffbf9fe
cagr          = -0.047082
```

> 注意：2026-11-26 已把正式快照重算为全文件 hash，当前版本是 `dv-91efdffbf9fe`。
> 上面的 `exp-8a...` 等实验绑定的是重算前的 `dv-036ee34e7f93`；两者数据内容相同，
> 但版本不同，不能混比。

### 4.4 核心动量实验重跑（2026-11-26）

在 `dv-036ee34e7f93`（重算前；同内容全文件版本 `dv-91efdffbf9fe`）上重跑两条真实数据动量实验：

| 区间 | 旧实验 | 新实验 | CAGR 旧→新 | Sharpe 旧→新 |
|---|---|---|---|---|
| 2021..2026 | `exp-156080bc8d3f` | `exp-8a290e55c2c0` | -6.4592% → -6.4747% | -0.2085 → -0.2104 |
| 2021..2024 | `exp-3e14b6dd0170` | `exp-8b52f86a07a2` | -7.7618% → -7.7841% | -0.2597 → -0.2625 |

结论：方向不变、幅度几乎不变（CAGR 差约 -0.02pp），除权假跳空不是这套动量策略亏损的原因。
完整对照见 `output/reports/core_rerun_comparison.md`。

### 4.5 AkShare 重建结果（2026-11-26）

| 项 | 值 |
|---|---|
| 目录 | `C:\AI_workspace\smartx_client\out\real40_pit_akshare_v4` |
| 标的 | **38 / 40**（000961、600068 拉取失败，后者含退市期） |
| 共同标的 / 日期 | 38 / 1,456 |
| 日收益差 p95 | **0.0486%** |
| 日收益差 max | **0.4999%**（601868 回退源误差） |
| 财报行数 | 1,156（TTM EPS + 每股净资产，公告日=法定截止日） |
| 财报共同期数 | 921 |

财报交叉验证结果不乐观：

- `book` 相对差中位数 **36.7%**，p95 494%；
- `earnings` 绝对差中位数 0.0256，p95 0.373。

主要原因是 baostock 的 `book` 是 `epsTTM / roeAvg` 反推，遇到低 ROE/异常季度会放大；
AkShare 用每股净资产，口径不同。**因此财报目前不能互相验证**，只能各自作为敏感性检查。

> 2026-11-26 重算后，AkShare v4 的全文件版本是 `dv-ae6e7c1d170c`；
> 重算前的 prices-only 版本是 `dv-30ed99e21f0d`。

### 4.6 全文件 `dv`（2026-11-26 修复）

之前 `dv` 只 hash `prices.csv`，改 fundamentals 不会换版本（P2-19）。现在：

- `manifest.snapshot_sha256` = schema/universe/adjust_mode + 所有文件 sha 的 SHA256；
- `manifest.data_version = "dv-" + snapshot_sha256[:12]`；
- `sha256` 字段仍保留为 prices-only，兼容旧快照/旧实验；
- 加载时校验每个文件 hash，篡改会直接 `DataError`；
- 旧 manifest 没有 `snapshot_sha256` 时继续按 prices-only 取版本，旧实验不漂移。

工具：`scripts/rehash_snapshot.py`（只重算 manifest，不重算数据）。
正式快照重算后：**`dv-91efdffbf9fe`**；`output/data/latest.json` 已指向它。

## 5. Agent 2 已接 `source` + 默认连续价

`refresh_snapshot` 现在支持：

```json
{"out_dir": "..._akshare", "base_dir": "..._baostock", "source": "akshare", "min_coverage": 0.8}
```

- 默认 `source=baostock`，行为不变；
- baostock 默认 `continuous=true`：用 preclose 链式连续价；base 不是连续价时回退全量；
- `source=akshare` 必须给 `base_dir`，复用其标的/日历/成分；
- AkShare 不支持增量，也不会返回 `noop`；
- 作业状态里记录 `source`；
- 仍由 `refresh_status` 轮询，成功后更新 `latest.json` 指针（与 baostock 相同）。

## 6. 已知限制

- AkShare 东财端点会限流/断连；Sina 回退源没有官方涨跌幅，除权日有误差；
- 000961、600068 仍拉不到，AkShare 只能到 38/40；
- 财报的 `available_date` 用的是法定截止日（保守，不是实际公告日）；
- baostock 的 `book` 由 `epsTTM/roeAvg` 反推，和 AkShare 每股净资产口径不同，**财报暂不可交叉验证**；
- AkShare 免费接口没有历史时点成分，只有当前成分；`compare_constituents.py` 只能核对最新一天；
- 旧快照没有 `snapshot_sha256` 时仍按 prices-only 取版本，无法追溯旧快照的 fundamentals 变更；
- `002085` 已用“不复权 + 涨跌幅”链式解决；`601868` 等回退源仍有 0.1–0.5% 误差。

## 7. 下一步

1. 把 `dv` 改成全文件 hash，避免 fundamentals 变更不换版本；
2. 000961/600068 用其他源（或人工导出）补齐，或明确从样本中剔除；
3. 若要真正做 PIT 成分交叉验证，需要引入有历史成分的数据源（付费/券商）；
4. 财报口径统一后，再决定 AkShare 是否能作为 value/quality 的第二源。
