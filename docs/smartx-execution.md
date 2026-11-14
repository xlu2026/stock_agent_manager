# SmartX 执行链路（2026-11-11 实测）

> 结论先行：**个人外部程序化下单在券商侧只剩一条路——SmartX 的 CSV 任务
> （`smartx-cli startCSV`）。** QMT/miniQMT 已关，SmartX Python 组件是沙箱，
> 不能读本地文件、不能收外部信号。CSV 这条路能下单、能撤单；下单确认仍需人工点，
> 但**委托/成交/持仓/资产已经可以自动导出**，仓库侧可以对账。

---

## 1. 为什么是这条链路

| 通道 | 状态 | 依据 |
|---|---|---|
| 券商 QMT / miniQMT | ❌ 个人已全部停用 | 客服口径；`xtquant.xttrader` 依赖 miniQMT，没有就无外部报单 |
| QMT 内置 Python 策略 | ⚠️ 只能在客户端里跑 | `ContextInfo`/`passorder`，无对外 API，拿不到我们的信号 |
| SmartX Python 组件 | ❌ 沙箱 | 客服明确：策略运行时不能读本地文件、不能接受外部信号 |
| SmartX 文件单（GUI） | ❓ 材料写“仅产品户” | 未验证 |
| **SmartX `startCSV`（CLI）** | ✅ **实测可用（账号类型正确时）** | 本文第 2 节 |
| SmartX 服务端功夫 | ⚠️ 托管 | 策略上传券商机房，破坏本地可复现边界 |

---

## 2. 实测记录

环境：SmartX 3.21.0，XTP 测试环境，`smartx-cli` v1.0.0，Windows。

### 2.1 CLI 只能交互式运行

- `smartx-cli.exe getWindows` 以参数形式启动、或从代理的 shell 里启动，都会**卡住无输出**
  （进程不退出、stdout 为空）。它需要真实控制台交互。
- 在 Windows Terminal 里手动运行正常：

```text
Welcome to smartx-cli tools V1.0.0
smartx>connected
smartx>getWindows
smartx>[0000][1,"<资金账号>"]
smartx>login <资金账号>
smartx>password:
smartx>[0000]登录成功
```

**含义**：短期内无法把 CLI 调用自动化；必须人工敲命令。这是当前“半自动”的硬约束之一。

### 2.2 路径必须是 ASCII

```text
smartx>startCSV C:\AI_workspace\材料\test_order.csv
smartx>[1060]ENOENT: no such file or directory, stat 'C:\AI_workspace\????\test_order.csv'
```

中文目录会被转成 `????`。所有交给客户端的文件放 **`C:\AI_workspace\smartx_client\`**
（`in\` 输入、`out\` 导出、`templates\` 样例）。

### 2.3 下单：解析 → 人工确认 → 报单

**首选 GUI 入口（2026-11-12 确认）**：客户端「下单 → CSV → 导入数据 → 选择上传」，
选中生成的 CSV 后核对并点「下单」。不需要 `smartx-cli`，也不需要登录命令行。

CLI 仍可用作后备：`startCSV <csv>` 返回 `[0000]启动成功` 后，客户端弹出
「普通交易CSV下单确认」，点「下单」之前不会报单（`orderInfo.csv` 一直只有表头）。

- 第一笔试单：价格 10.00，`[0000]`，确认后报单 → 委托状态 **已拒绝**，
  原因 `价格超出涨跌停范围[ID:...]`。说明链路通、价格不合法。
- 第二笔：换到正确的账号类型，价格 11.81 → 委托状态 **未成交**，无错误。
- 撤单：用导出文件里的 `ID` 生成 `2,<账号>,<orderXtpId>,` → `[0000]` → 确认 →
  委托状态变 **已撤**。

**结论**：CSV 解析、账号校验、报单、撤单四条都通；`status csv` 的“已停止”
只表示导入任务结束，不代表成交。

### 2.4 委托/成交：自动导出（2026-11-12 起）

客户端「设置 → 系统设置 → 自动导出设置」可以定时把 6 个 CSV 写到固定目录：

```
C:\AI_workspace\smartx_client\out\orders\
  xtp_<账号>_Order.csv          委托
  xtp_<账号>_Trade.csv          成交
  xtp_<账号>_Position.csv       持仓
  xtp_<账号>_Asset.csv          资产
  xtp_<账号>_algoList.csv       算法母单
  xtp_<账号>_algoTickerList.csv 算法子单
```

- 文件名固定、不带日期，**每轮整份覆盖**；不是事件流，对账要按 `ID`（orderXtpId）/
  `成交编号` 合并，不能靠“来了新文件”判断。
- 当前实测设置：定时导出开启、间隔 **120 秒**；`closeData\` 预留给收盘导出。
- 编码 UTF-8（带 BOM 也能读），部分字段带前导制表符，解析时要 `strip()`。
- Order 关键列：`ID`、`报单状态`、`委托数量`、`成交数量`、`剩余数量`、`撤销时间`、
  `错误原因`、`错误ID`、`rowId`、`渠道`。
- Trade 关键列：`成交编号`、`ID`、`成交价格`、`成交数量`、`成交时间`、`成交金额`。

仓库侧已实现只读解析与对账：

```powershell
python scripts\reconcile_smartx.py --dir C:\AI_workspace\smartx_client\out\orders
python scripts\reconcile_smartx.py --archive   # 另存一份带时间戳的归档
```

**不再需要人工去「今日委托」页导出 zip。**

---

## 3. CSV 格式（普通交易）

一行一笔，`0` 表示文件结束：

```text
1,<资金账号>,<证券代码>,<价格>,<数量>,<价格类型>,<买卖>,<业务类型>,<委托号>,
0
```

- `1` = 报单，`2` = 撤单，`0` = 结束
- 价格类型 `1` = 限价
- 买卖 `1` = 买，`2` = 卖
- 业务类型 `0` = 普通（两融用样例里的 4 / 21 / 22）
- 撤单行：`2,<资金账号>,<orderXtpId>,`
- 行尾 **CRLF**，编码 UTF-8 无 BOM（纯 ASCII 最稳）
- 官方样例：`%LOCALAPPDATA%\Programs\xtp_rich_client\doc\order_csv_sample.csv`

---

## 4. 当前可用的操作流程（半自动）

```text
仓库算目标持仓 / 生成提案
  → python scripts\make_smartx_csv.py --proposal <id> --account <账号>
     （生成 in\orders_YYYYMMDD_HHMMSS.csv；rowId = 提案 id）
  → 人工在客户端「下单 → CSV → 导入数据 → 选择上传」选中 CSV
  → 人工核对并点「下单」
  → SmartX 每 120 秒自动导出 6 个 CSV 到 out\orders\（整份覆盖）
  → python scripts\reconcile_smartx.py 按 rowId 对账
  → 收盘后 --archive 归档一份，避免被下一轮覆盖
```

**约束**：仍然是两次人工操作（选文件上传、点「下单」）。GUI 入口不需要登录
`smartx-cli`；自动导出只解决“看结果”，没有改变“下单必须人工批准”的边界。

对账口径：

- `Order.csv` 的 `rowId` 对上提案 id；`ID` 是 orderXtpId，撤单用它；
- 状态机：`未成交 → 部分成交 → 已成交 / 已撤 / 已拒绝`；
- `成交数量` 是累计值，直接覆盖，不做累加；
- `Trade.csv` 按 `成交编号` 去重；
- 拒单看 `错误原因` / `错误ID`；撤单看 `撤销时间`。

---

## 5. 未决问题（等中泰答复）

1. 下单确认框（GUI 的「下单」/ CLI 的确认）能否关闭（免确认）？关闭后是否仍合规？
2. ~~委托/成交能否自动导出~~ ✅ 已支持（定时导出，2026-11-12 确认）；待确认：
   收盘导出的文件命名/是否覆盖 `closeData\`、以及导出是否包含历史委托（当前是当日快照）。
3. 生产账户的**账号类型**是否与测试通过的这一类型一致？
4. 个人账户使用 CSV 任务是否需要额外的程序化交易报备字段（软件名称、渠道）？

第 1 条决定能不能往“无人值守”走；第 3 条决定这套方案能不能落到实盘。

---

## 6. 对接实现

### 6.1 生成下单 CSV（已实现）

`quant/broker/smartx_csv.py` + `scripts/make_smartx_csv.py`：

```powershell
python scripts\make_smartx_csv.py --proposal prop-xxxxxxxxxx --account 12345678
python scripts\make_smartx_csv.py --proposal prop-a --proposal prop-b --quotes quotes.json
python scripts\make_smartx_csv.py --cancel 40126371980117969 --account 12345678
python scripts\make_smartx_csv.py --proposal prop-x --dry-run
```

- 格式：`1,账号,600000.SH,价格,数量,1,买卖,0,rowId,` + 结尾 `0`，CRLF、UTF-8 无 BOM；
- 代码统一成 `600000.SH` / `000001.SZ`（官方样例带后缀）；
- `rowId` 用提案 id，导出后按它就能对回提案；
- **价格必须是不复权价**：先跑
  `python scripts\fetch_quotes.py --symbols 601939.SH --out output\broker\quotes.json`，
  再用 `--quotes output\broker\quotes.json` 生成；
- 没有 `quotes` 时默认拒绝生成；只有显式 `--allow-unchecked` 才会用快照价（后复权，可能被拒单）；
- 校验：账号数字、数量 > 0、价格 > 0、代码合法、买卖方向；有 quotes 时校验涨跌停；
- 审计：CSV 旁写 `.json`（含 sha256、提案列表），并追加 `output/broker/smartx_csv/index.jsonl`；
- 幂等：同一提案默认只能生成一次（`--allow-repeat` 可覆盖）；
- **只生成文件**，不调用 `startCSV`、不点「选择上传」、不提交、不碰券商。

> 2026-11-12 实测踩坑：第一版用快照价 `30.3099` 生成买单，客户端直接以
> `价格超出涨跌停范围` 拒单。根因是快照为后复权，而 `601939.SH` 当日名义收盘价是 `11.92`。
> 下单价格必须走 `fetch_quotes.py` 的不复权价。

生成后的 GUI 操作：客户端「下单 → CSV → 导入数据 → 选择上传」选中该文件 → 核对 → 点「下单」。

### 6.2 导出对账（已实现）

`quant/broker/smartx_export.py` + `scripts/reconcile_smartx.py`：

- 只读解析 6 个 CSV，按表头映射、去前导 tab、兼容 UTF-8/BOM/GB18030；
- 按 `rowId` 把委托对回提案，输出 matched / unmatched / rejected；
- `--archive` 把当前快照复制到 `archive\<时间戳>\`。

### 6.3 仍待做

- `SmartXCsvBroker` 作为 `Broker` 适配器接入统一接口（目前是独立脚本）；
- 批量生成/撤单自动化（撤单仍需人工在 GUI 上传或 CLI `startCSV`，并点确认）；
- 客户端是否接受带连字符的 `rowId`、是否对同一 `rowId` 去重，需实盘验证。
