# QMT 信创模拟交易端调查（2026-11-25）

安装路径：`C:\AI_workspace\_tools\中泰qmt信创模拟交易端`
主要组件：`bin.x64\XtItClient.exe`（完整客户端）、`XtMiniQmt.exe`（miniQMT 模式）、
`minibroker.exe` / `miniquote.exe`。

## 1. 能不能拉数据

**终端本身：能。** 本地已有下载好的数据：

| 目录 | 规模 |
|---|---|
| `datadir` | 3,015 个文件，约 159 MB |
| `userdata_mini\datadir` | 859 个文件，约 86 MB |

完整客户端在 2026-11-13 20:51 登录成功（模拟账号已脱敏），日志里有
`login status: 12 description: 登录成功`，随后有 `AutoRunStrategy ... login success`。
说明终端能登录、能下载行情。

**外部 Python 程序化拉数据：当前不能。** 原因是缺 `xtquant`：

- 仓库 Python 3.12：`import xtquant` → `ModuleNotFoundError`；
- SmartX 自带 Python 3.9：同样 `ModuleNotFoundError`；
- 安装目录里没有 `xtquant` 目录，也没有 `xtdata.py` / `xttrader.py`；
- `XtMiniQmt.exe` 存在，但 miniQMT 登录被拒：
  `proxy_login_status status = 23, message = 请联系券商开通对应权限`（2026-11-13 13:55）。

所以“QMT 能拉数据”分两层：

- **人用终端**：能，界面里看行情、下载数据；
- **程序用 `xtdata`**：不能，缺包；即使补包，miniQMT 权限也没开。

可选路径：

1. 从 QMT **投研端**（不是这个交易端）复制同版本 `xtquant` 包过来，再开 miniQMT；
2. 在 QMT 里跑内置 Python 策略，用 `ContextInfo.get_market_data` / `get_full_tick`
   取数，把结果写成 CSV，再走仓库的 `csv_import`；
3. 手动用 QMT 的数据导出功能导 CSV；
4. 继续用 baostock（Agent 2 已跑通）。

## 2. 怎么提单

### 2.1 GUI 手动

登录完整客户端 → 交易 → 买入/卖出，或篮子/组合交易。适合人工，不进入仓库审计链路。

### 2.2 QMT 内置 Python 策略

QMT 自带 Python 策略示例在 `python\*.py`，用的是客户端注入的 `ContextInfo` 与全局函数：

```python
# 取数（策略内）
close = ContextInfo.get_market_data(['close'], period=ContextInfo.period,
                                    dividend_type=ContextInfo.dividend_type)

# 下单（策略内，示例见 python\PY组合模型.py）
order_shares('600000.SH', 100, 'fix', price, ContextInfo, ContextInfo.accountID)
```

- 这是**客户端内**的自动化，不是外部程序；
- 策略能读写本地文件，可以“取数/下单 → 写 CSV/日志”；
- 需要客户端登录且账号有对应交易权限。

### 2.3 外部 Python（xtquant）

标准写法是：

```python
from xtquant.xttrader import XtQuantTrader
from xtquant import xtconstant

trader = XtQuantTrader(path, session_id)
trader.start()
trader.connect()
trader.subscribe(account)
trader.order_stock(account, '600000.SH', xtconstant.STOCK_BUY, 100,
                   xtconstant.FIX_PRICE, 11.92)
```

但本机：

- 没有 `xtquant` 包；
- miniQMT 登录被拒（权限未开）；
- 完整客户端登录成功不等于 miniQMT/xtquant 通道可用。

## 3. 对本项目的建议

- **数据**：继续 baostock + Agent 2，已验证；QMT 数据先作为人工交叉校验，不接自动链路。
- **下单**：继续 SmartX CSV（已验证 GUI 上传 → 报单 → 自动导出 → 对账）。
  QMT 若要接，先解决两件事：`xtquant` 包 + miniQMT 权限；在此之前不要把它写进
  Agent 1 的工具面。
- 若要用 QMT 内置策略，建议单独做一个“QMT 策略 → CSV”的导出器，
  不要和 SmartX 的订单链路混在一起。

## 4. 未验证 / 待确认

- `xtquant` 是否随投研端提供、版本是否必须与交易端一致；
- miniQMT 权限能否由中泰开通（当前 status 23）；
- QMT 内置策略写文件的目录权限与编码（GBK/UTF-8）；
- QMT 下载数据的复权口径与 baostock 是否一致（需抽样对比）。
