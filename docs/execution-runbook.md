# 执行 Runbook（QMT / SmartX）

> 当前只做模拟盘与人工执行；不接实盘、不自动启动、不代客。
> 所有策略文件都是“生成 + 人工导入”，QMT 没有公开的注册/启动 API。

## 1. 两种模式

| 模式 | 文件 | 用途 |
|---|---|---|
| 历史回测 | `output/qmt/nfr_mom_lowvol.py` | 验证 QMT 与引擎的偏差 |
| 前向 paper | `output/qmt/nfr_mom_lowvol_paper.py` | 模拟盘按真实时间跑 |

版本：

- 回测冻结：sha `089dfd...`，TE 4.22%；
- paper：sha `9766768f...`，动态月度、追加 NAV。

## 2. QMT 历史回测

1. QMT → 新建 Python 策略；
2. 粘贴回测版（GBK）；
3. 编译；
4. 设区间、基准 000300、模拟账户、日线；
5. 回测；
6. 记录 NAV 到 `output/qmt/nfr_mom_lowvol_nav.csv`。

已知偏差：

- 同 bar 卖出回款不可用 → 部分买单跳过；
- 100 股整手；
- QMT 行情 vs baostock；
- 不追两阶段，接受 TE 约 4–6%。

## 3. QMT Paper

1. 新建策略，粘贴 `nfr_mom_lowvol_paper.py`；
2. 确认 `PAPER=True`、`REBALANCE_DATES=[]`；
3. 编译；
4. **模型交易 → 新建策略交易**，选模拟账户、日线；
5. **每月第一个交易日**调仓；不要从月末启动（会连续触发）；
6. 保持 QMT 运行到收盘。

每日：

- 收盘后检查 NAV 是否追加；
- 记录 orders/trades/positions/incidents；
- 备份 NAV 与 `.state`。

关机前：先停止策略 → 关 QMT → 关机。
次日开盘前：开 QMT → 登录 → 启动策略。

## 4. 启动检查

```text
PAPER = True
REBALANCE_DATES = []
NAV_PATH = ...paper_nav.csv
STATE_PATH = ...paper_nav.csv.state
```

账户来自 `config/qmt.json`；必须是模拟账户。

## 5. 常见异常

| 现象 | 处理 |
|---|---|
| `可用资金不足` | 同 bar 现金限制；记录跳过单，不改成实盘逻辑 |
| `过滤零股后下单量 0` | 100 股整手；记录 |
| `NAV export failed` | QMT 禁止写文件；手工导出 |
| `state write failed` | 检查路径/权限；重启可能重复调仓 |
| 没有 `rebalance` | 未到调仓日、策略停止、周期/账户错 |
| QMT 关闭/睡眠 | 不会补跑；记录缺失日 |

## 6. 代码/配置版本

- 生成文件 sha 在 `output/qmt/*.py.json`；
- 粘贴到 QMT 后无法自动校验 sha；
- 每次换代码，先在 `docs/experiment-ledger.md` 记录；
- 账户配置 `config/qmt.json` 已 gitignore，示例 `config/qmt.example.json`。

## 7. 不做的

- Agent 4 自动部署/启动；
- QMT 自动登录/自动点启动；
- 两阶段调仓（除非同时改引擎）；
- 实盘下单。
