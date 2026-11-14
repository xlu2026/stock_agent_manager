# LLM 调用 Agent 的提示词教程

这份教程只讲一件事：**你该对 Agent 说什么**。
Agent 的“系统提示词”已经写死在 profile 里（`cordis/prompts/*.md`），启动时自动加载；
你每次输入的是“用户提示词”，只写任务，不要把系统提示词再粘贴一遍。

---

## 0. 先分清两层提示词

| 层 | 位置 | 谁写 | 作用 |
|---|---|---|---|
| 系统提示词 | `cordis/prompts/agent1.md` / `agent2.md` / `agent3.md` | 仓库维护者 | 角色、边界、工具、输出格式 |
| 用户提示词 | 你每次在 `dsh` 里输入的那句话 | 你 | 这一次要做什么 |

改系统提示词要跑 `tools/build_cordis.py` + `tools/install_dsh_profile.py`；
日常使用只写用户提示词。

---

## 1. 三种调用方式

```powershell
# Agent 1：量化研究
dsh --profile quant "用沪深300跑一次动量回测，区间 2021-01-04~2024-12-31"

# Agent 2：数据刷新
dsh --profile agent2 "增量刷新最新快照到今天"

# Agent 3：写公众号草稿
dsh --profile writing "读 briefs/002-momentum-package.json，写成公众号草稿"
```

- 加 `--json` 可以看到工具调用过程（`tool_call` / `tool_result` 事件）；
- 一次性任务结束就退出；需要多轮追问，用 Web/TUI 会话或 `--session-id`；
- Web 里的三个 preset（量化研究 / 数据运维 / 公众号写作）是生成的，**未实测**，CLI 最稳。

---

## 2. 通用写法：目标 + 对象 + 约束 + 期望输出

一条好的提示词包含四块：

1. **目标**：做什么（跑回测 / 刷新数据 / 写文章）；
2. **对象**：哪个池、哪个区间、哪份简报；
3. **约束**：不要做什么（不要覆盖、不要发布、不要选因子）；
4. **期望输出**：要哪些字段、落到哪。

反例：

> “帮我看看动量行不行。”

问题：没池、没区间、没说“行”指什么。Agent 只能追问或瞎猜。

正例：

> “用 `synthetic_40` 跑一次动量回测，区间 `2020-01-02~2024-12-31`，
> 报告 experiment_id、cagr、sharpe、max_drawdown、ic_mean，并说明映射到哪个因子。”

---

## 3. Agent 1（量化研究）

### 3.1 它期待四字段

Agent 1 的服务端只认这四个字段：

| 字段 | 说明 | 例子 |
|---|---|---|
| `question` | 研究问题，只做记录 | “过去一年涨得多的会不会继续涨” |
| `universe` | 标的池 | `synthetic_40` / `沪深300` |
| `period` | 起止日期 | `2020-01-02~2024-12-31` |
| `factor_logic` | 自然语言因子逻辑 | “过去 12 个月的动量，剔除最近 1 个月” |

`factor_logic` 里**不要写因子代码**（如 `momentum_12_1`），服务端用关键词表映射；
写了代码也不会被当成因子名。

### 3.2 关键词表（决定映射到哪个因子）

| 因子 | 可用关键词 |
|---|---|
| `momentum_12_1` | 动量、趋势、强势、惯性、涨势、追涨 |
| `value_proxy` | 估值、便宜、低估、账面、价值、pb |
| `low_vol_60d` | 波动、低波、风险、稳健、回撤 |
| `quality_proxy` | 质量、roe、盈利、赚钱、基本面、现金流 |

一句话里同时出现两个因子的关键词（如“低波动且估值便宜”）会被判 `FACTOR_AMBIGUOUS`，
这是故意的：先澄清，不要让它猜。

### 3.3 模板

```text
用四字段研究指令跑一次回测：
- question: 过去一年涨幅靠前的标的，接下来一个月是否继续走强？
- universe: synthetic_40
- period: 2020-01-02~2024-12-31
- factor_logic: 过去 12 个月的动量，涨幅靠前的标的在接下来一个月是否延续强势

报告 experiment_id、cagr、sharpe、max_drawdown、annual_turnover、ic_mean，
并说明 factor_logic 被映射成了哪个因子。不要自己估算任何数字。
```

真实数据版：

```text
用沪深300跑一次动量回测，区间 2021-01-04~2024-12-31。
数据来自当前服务端配置的真实快照；报告 experiment_id、cagr、sharpe、max_drawdown、
ic_mean、data_version，并注明真实数据的样本与口径限制。
```

### 3.4 真实数据的前提

Agent 1 的 LLM 会话**不能靠提示词切换快照**。数据源是 MCP 服务端启动时的环境变量：

```powershell
$env:NFR_DATA_DIR = "C:\AI_workspace\smartx_client\out\real40_pit"
dsh --profile quant "用沪深300跑动量回测，区间 2021-01-04~2024-12-31"
```

- `universe` 写 `沪深300`（服务端映射到 `hs300_40_pit`）；
- 池名和快照不匹配会报 `UNIVERSE_UNAVAILABLE`；
- 想换快照就重开会话并改 `NFR_DATA_DIR`，不要在对话里让 Agent“换个目录”。
- Python 入口（非 LLM）可以用 `--latest` 读最新快照指针；LLM 会话没有这个参数。

### 3.5 补充证据

```text
对刚才那个动量指令再做一次因子分析，quantiles=5，报告 IC 序列均值、IC_IR 和分位收益。
```

```text
用同一个指令跑一次历史模拟盘，sessions=20，只输出 PAPER 台账，不产生订单。
```

### 3.6 错误怎么问

```text
如果工具返回 FACTOR_UNMAPPED / FACTOR_AMBIGUOUS / UNIVERSE_UNAVAILABLE 或校验失败，
把原始错误码和原因贴出来，不要换说法重试。
```

### 3.7 下单（只有模拟通道）

```text
用 exp-xxxx 的最新持仓，给其中 3 个标的各提一个 PAPER 买单草案，数量 100 股。
只生成提案，不要提交；把 approve_command 原样给我。
```

不要说“帮我买”，也不要说“提交吧”——除非你已经人工批准了提案。

---

## 4. Agent 2（数据刷新）

### 4.1 触发条件

只在**明确说“刷新/拉数据/更新行情”**时才会动手；不说就不动。

### 4.2 模板

增量：

```text
增量刷新数据：以现有最新的时点快照为基线，拉到今天。
out_dir 用 <基线目录>_<今天日期>，不要覆盖旧目录。
启动后轮询到结束，报告 job_id、state、新 data_version、区间、体检结果；
如果返回 noop，直接说“已是最新”。
```

全量：

```text
全量刷新行情和财报，输出到 C:\AI_workspace\smartx_client\out\real40_pit_full_20261111。
不要复用旧目录。完成后报告 data_version、区间、标的数和体检结论。
```

取消卡住的作业：

```text
job-20261111-203253-c2f2 卡住了，先查状态；如果还在 running，取消它并告诉我错误。
```

清理旧作业：

```text
清理作业目录，保留最近 10 个，先 dry_run 给我看要删哪些。
```

### 4.3 它会做什么

1. `list_snapshots` 找基线（`end` 最大且 `point_in_time=true`）；
2. `refresh_snapshot` 启后台作业；
3. `refresh_status` 轮询（`wait_seconds` 20–30）；
4. 失败时读日志、最多重试一次；网络类错误才重试；
5. 成功后报告新 `dv`，并说明已更新 `output/data/latest.json`。

### 4.4 失败怎么问

```text
如果作业 failed，把 status 里的 error、exit_code、log_tail 原样贴出来，
不要改日期或换目录反复重跑。
```

---

## 5. Agent 3（公众号写作）

### 5.1 先准备素材包

Agent 3 只吃 `briefs/` 里的 JSON 简报，不直接读实验记录。把素材放到：

```
C:\AI_workspace\wechat_writing\briefs\<名字>.json
```

简报字段见系统提示词第一节：`experiment_id / data_source / research_question /
factor_logic / backtest_summary / user_notes / target_structure`。

### 5.2 模板

```text
读 briefs/002-momentum-package.json，按你的系统提示词写成公众号草稿。
保存到 articles/2026-11-11-momentum-failure.md，只到草稿，不要发布。
data_source 按简报里的值填；如果简报是 synthetic，正文必须带合成数据声明。
```

### 5.3 合规红线

不要在提示词里要求它：

- 写个股代码、买卖点、收益承诺；
- 把合成数据说成实盘业绩；
- 调用发布接口或自动发布。

如果素材里没有某个事实，要求它输出“素材不足，需补充：……”，不要编。

### 5.4 好/坏例子

坏：

> “把这次动量回测写成爆款，标题夸张一点，带上涨得最好的几只票。”

好：

> “按简报写一篇复盘，重点写‘我原以为动量会延续、结果被打脸’的过程；
> 标题不超过 20 字，不要个股代码，不要收益承诺，文末加固定风险提示。”

---

## 6. 三个 Agent 怎么串

一条完整链路：

```text
Agent 2  → 刷新快照，报告 dv 和目录
   ↓（人把 NFR_DATA_DIR 指过去，重开 quant 会话）
Agent 1  → 跑回测，拿到 experiment_id 和指标
   ↓（人把指标整理成 briefs/*.json）
Agent 3  → 写草稿，落 articles/
```

对应提示词：

```text
# Agent 2
增量刷新数据到最新，报告 data_version 和目录。

# Agent 1（重开会话，先设 NFR_DATA_DIR）
用沪深300跑动量回测，区间 2021-01-04~2024-12-31，报告 experiment_id 和指标。

# Agent 3
读 briefs/003-xxx.json，写成公众号草稿，只到草稿箱。
```

不要在一个会话里让 Agent 3 兼做回测，也不要让 Agent 1 写文章——工具面和提示词都不支持。

---

## 7. 怎么确认提示词真的生效

加 `--json` 看事件流：

```powershell
dsh --profile quant --json "用 synthetic_40 跑动量回测，2020-01-02~2024-12-31"
```

你会看到：

- `tool_call`：调了 `mcp__srq__run_research_instruction`，参数是四字段；
- `tool_result`：返回 `experiment_id`、`metrics`、`contract`；
- 最终 `text`：按格式汇报。

验收侧还可以看：

| Agent | 落盘证据 |
|---|---|
| Agent 1 | `experiments/exp-*.json`、`output/reports/agent1_latest.json` |
| Agent 2 | `output/data_jobs/<job_id>/status.json`、`output/data/latest.json` |
| Agent 3 | `C:\AI_workspace\wechat_writing\articles\*.md` |

---

## 8. 常见坑

| 坑 | 后果 | 正确做法 |
|---|---|---|
| 在 `factor_logic` 里写因子代码 | 关键词表可能匹配不到 | 用自然语言关键词（动量/估值/波动/质量） |
| 一句话塞两个因子 | `FACTOR_AMBIGUOUS` | 拆成两次，或先澄清 |
| 让 Agent 1 “用最新数据”但没设 `NFR_DATA_DIR` | 仍读旧快照 | 启动前设环境变量，重开会话 |
| 让 Agent 1 自己估收益 | 违反确定性边界 | 只让它转述工具返回的数字 |
| 让 Agent 2 覆盖旧快照目录 | 旧实验无法复现 | 每次新目录 |
| 让 Agent 2 反复重跑失败作业 | 浪费时间和 token | 网络类只重试一次，然后报告 |
| 让 Agent 3 读 `experiments/` | 可能带出个股代码 | 只给它 `briefs/` 素材包 |
| 让 Agent 3 发布 | 越过人工闸门 | 只到草稿箱，发布手动 |
| 把系统提示词再粘贴一遍 | 冗余、可能冲突 | 只写任务 |

---

## 9. 速查表

| 你想做什么 | Profile | 一句话模板 |
|---|---|---|
| 合成数据跑动量 | `quant` | “用 synthetic_40 跑动量回测，2020-01-02~2024-12-31，报告实验 ID 和指标” |
| 真实数据跑价值 | `quant` | “用沪深300跑价值回测，2021-01-04~2024-12-31，报告 IC 和回撤” |
| 补充 IC 证据 | `quant` | “对刚才的指令做因子分析，quantiles=5” |
| 历史模拟盘 | `quant` | “用同一指令跑 20 次模拟盘，只输出 PAPER 台账” |
| 增量刷新 | `agent2` | “增量刷新最新快照到今天，报告 dv 和体检” |
| 全量刷新 | `agent2` | “全量刷新到 <新目录>，报告 dv” |
| 取消卡住作业 | `agent2` | “取消 job-xxx，报告错误” |
| 清理旧作业 | `agent2` | “清理作业目录，保留最近 10 个，先 dry-run” |
| 写一篇复盘 | `writing` | “读 briefs/xxx.json，写成草稿，只到草稿箱” |
