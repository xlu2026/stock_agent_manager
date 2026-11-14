# Phase 1 验收报告

> **历史文档（Phase 1，2026-11-08）**：本报告记录当时的验收结论。之后新增了
> Agent 2 数据刷新、真实 baostock 快照、SmartX CSV 半自动执行和发布台；
> 当前架构见 [architecture.md](architecture.md)，当前状态见 [handoff.md](handoff.md)。
>
> 生成环境：Windows，Python 3.12.8（`C:\Program Files\Python312\python.exe`），
> DSH Desktop 0.2.2-rc.1，工作区 `C:\AI_workspace\stock_agent_manager`。
> 全部结论均可由 `python scripts\acceptance.py` 复现。

---

## 0. 环境事实（先说清楚，后面的结论都建立在这上面）

| 项 | 简报假设 | 实际情况 | 处理 |
|---|---|---|---|
| SolidRockQuant `srq` | 已安装，`srq mcp serve` | 机器上不存在；PyPI 不可达 | 按约定工具面自建 `srq-compat`，命令与工具名保持不变 |
| `deepseek-harness-sdk` | 控制平面 | PyPI 无此包，且外网仅 DeepSeek API 可达 | 控制平面改用本机真实存在的 `dsh` CLI + Cordis profile |
| 行情数据源 | 未指定 | 无外网行情、无 vendor SDK | 固定种子合成样本 + sha256 快照 |
| 公众号凭据 | 未知 | 已配置：AppID `wx0e04fdba2871bad4`，AppSecret 在本地 `.env`，出口 IP 已加白名单 | 草稿箱接口实测可用，开篇草稿已写入 |
| 第三方 Python 包 | 未指定 | **一个都没装**，PyPI 不可达 | 全链路只用标准库（含 MCP 协议、HTTP、YAML 生成） |

这条决定了整个实现风格：**零第三方依赖**。所以"依赖是否兼容 Python 3.12"的答案是
"没有依赖可兼容"——直接用 Python 3.12.8 跑通，不存在版本冲突面。

---

## 1. 必答问题

### 问题 1：个人订阅号的 `draft/add` 是否可用？

**结论：`DRAFT_API_AVAILABLE` —— 有权限。已于 2026-11-07 实测并成功写入草稿箱。**

验证过程分三步，每一步都留下了痕迹：

1. **无凭据阶段**：只能报 `DRAFT_API_UNAVAILABLE / NO_CREDENTIALS`，这是"未验证"，不是"被拒绝"，当时没有把它当成结论。
2. **补凭据后**：先撞 `40164`（出口 IP 不在白名单），微信在 errmsg 里回显了 IP `171.223.68.xxx`，加入白名单后通过。
3. **权限判定**：只读探测 `draft/get` 返回 `40007 invalid media_id`——说明接口已授权，只是占位 ID 不存在。随后 `draft/add` 真实创建草稿成功，`draft/batchget` 回查 `total_count: 1`。

期间还修掉一个会误报的 bug：微信的错误有两种形态（HTTP 4xx 抛异常 / HTTP 200 + body 里的 errcode），
原实现只在抛异常时判失败，会把 `48001` 也当成"可用"。现已按 errcode 分类，并补了 4 条回归测试。

| 探测结果 | 脚本输出 | 含义 |
|---|---|---|
| `cgi-bin/draft/get` 返回 48001 / 48004 | `DRAFT_API_UNAVAILABLE` / `API_UNAUTHORIZED` | 没有草稿箱权限 |
| token 阶段 40164 | `DRAFT_API_UNAVAILABLE` / `TOKEN_FAILED` | 出口 IP 不在白名单 |
| token 阶段 40125 / 40013 | `DRAFT_API_UNAVAILABLE` / `TOKEN_FAILED` | AppSecret / AppID 错误 |
| 读草稿返回 40007（占位 media_id 被拒） | `DRAFT_API_AVAILABLE` | 接口已授权 |

设计上刻意**不**用 `draft/add` 做探测：那会在后台凭空创建一篇草稿。改用只读的
`draft/get` + 占位 `media_id`，把"权限不足"和"media_id 不存在"区分开。

账号的实时状态、白名单 IP、变现开通进度都记在 [wechat-account.md](wechat-account.md)，不在本报告里重复。

证据：[`output/reports/draft_precheck.json`](../output/reports/draft_precheck.json)、
[`output/reports/push_draft_latest.json`](../output/reports/push_draft_latest.json)。

### 问题 2：DSH 在 Windows / Python 3.12.8 下加载 Cordis 配置、连接 SRQ MCP stdio 是否正常？

**结论：正常，且已用真实模型跑通工具调用。**

分三条讲：

1. **Python 3.12.8 兼容**：整条链路只用标准库，`python -m quant.cli doctor` 直接可用。
2. **Cordis 配置加载**：自定义 profile（`~/.dsh/profiles/quant`）由 `dsh --profile quant --dump-config`
   成功组合；`writing` 同样成功。两个 profile 的组合结果分别留证在
   [`composed_config_quant.txt`](../output/evidence/composed_config_quant.txt) 与
   [`composed_config_writing.txt`](../output/evidence/composed_config_writing.txt)。
3. **MCP stdio 连接**：`dsh` 启动时会 spawn 服务端，stderr 出现
   `[srq-compat] ready on stdio (protocols: 2026-07-28, 2025-11-25, 2025-06-18, ...)`，
   会话结束后正常关闭。模型真实发出的调用记录见
   [`dsh_quant_tool_call.jsonl`](../output/evidence/dsh_quant_tool_call.jsonl)：

   ```
   CALL mcp__srq__list_experiments {"limit": 3}
   FINAL ... 1. exp-a359c2d77697 ... nav_hash: fc5c9e77... 
   ```

**关键发现（会影响 Phase 2 设计）**：`dsh headless` 一次性入口**不支持** agent preset。
源码 `dsh-headless/lib/index.js:227` 直接抛错："session ... runs under agent preset ...,
which the one-shot runner does not compose"。所以：

- Phase 1 的隔离用 **profile 级**（两个 profile，各自一份 patch）——已验证可用；
- `cordis/phase1-presets.yml` 按 preset 形式保留，供 Web 会话按会话选 preset 时使用。

### 问题 3：SolidRockQuant 工具面在 DSH 中是否可发现、返回格式是否适合 Agent 消费？

**结论：可发现（6/6），且格式适合 Agent 消费。**

`python scripts\verify_mcp.py` 走完整 JSON-RPC 握手（initialize → tools/list → tools/call），
10 项断言全部通过：

| 工具 | 结果 |
|---|---|
| `run_backtest` | 返回 `structuredContent`，含 `experiment_id`、15 个指标、`provenance` |
| `validate_strategy` | 返回逐条 pass/warn/fail 诊断 |
| `list_experiments` | 返回 `count` + 摘要列表 |
| `get_experiment` | 按 ID 取回完整记录（可选净值序列） |
| `run_factor_analysis` | 返回 IC 均值/IR/t 值/分位收益/单调性 |
| `run_paper_session` | 返回模拟成交台账，`live_orders: false` |

适配性设计：每个工具都有 `inputSchema`（含 `additionalProperties: false`），成功结果同时给
`content[].text`（人/模型可读的 JSON 文本）和 `structuredContent`（程序可读），错误走
`isError: true` 而不是伪造成功。模型实测能正确复述 `experiment_id` 与 `nav_hash`，
说明格式没有歧义。

证据：[`mcp_protocol_verify.json`](../output/evidence/mcp_protocol_verify.json)。

---

## 2. 交付物

### 交付物 1：Agent 1 完成一次真实因子回测，返回指标和实验 ID

```powershell
python scripts\run_agent1.py --instruction examples\research_instruction.json
```

输入是任务书 3.2 规定的四字段契约：

```json
{"question": "过去一年涨幅靠前的标的，接下来一个月是否继续走强？",
 "universe": "synthetic_40",
 "period": "2020-01-02~2024-12-31",
 "factor_logic": "过去 12 个月的动量：涨幅靠前的标的在接下来一个月是否延续强势（趋势延续）"}
```

`factor_logic` 由服务端关键词表映射为 `momentum_12_1`（返回里带 `contract.mapping`），
模型不能自行指定因子。

实测结果（2020-01-02 → 2024-12-31，月度调仓，top 8，成本 10bps）：

| 指标 | 值 |
|---|---|
| experiment_id | `exp-a359c2d77697` |
| nav_hash | `fc5c9e778707e5f1280d1084c4018342aa4013a248e9aec2b3b2391b64a47f1a` |
| cagr | 0.1115 |
| sharpe | 1.4186 |
| max_drawdown | -0.143247 |
| annual_turnover | 2.2015 |
| 相对基准超额 | +0.070726 |
| 调仓次数 | 60 |

同一 spec 连跑两次，`nav_hash` 与整条净值序列逐位相同（有单测守着）。
记录：`experiments/exp-a359c2d77697.json`；信封：`output/reports/agent1_latest.json`。

说明：这些数字来自**合成样本**，只证明链路正确，不代表任何真实收益。

### 交付物 2：Agent 3 降级路径生成带 front matter 的 Markdown

```powershell
python -m agents.agent3 --brief examples\brief_demo.json
```

→ `C:\AI_workspace\wechat_writing\articles\[量化研究_001] 2026-11-08-factor-to-backtest-001.md`（确定性渲染，1134 字；文件名取渲染当天日期，
目录只保留最新一份）。
front matter 含 `schema/title/slug/date/status/author/series/category/phase/tags/summary/
experiment_ref/data_source/word_count/compliance/generated_by/render_path`；
正文含逐字合成数据声明，文末为 `---` + 实验 ID + 一句风险提示。

同时验证了模型驱动的路径（素材包契约见 `examples/research_package.json`）：
`writing` profile 的 Agent 3 读 `C:\AI_workspace\wechat_writing\briefs\002-momentum-package.json`，
按新提示词写出 `C:\AI_workspace\wechat_writing\articles\[存档] 2026-11-07-momentum-package.md`
（1440 字，合规 0 违规、文风自检 0 警告，合成数据声明与风险提示均逐字命中）。

### 交付物 3：`check_wechat_draft.py` 给出明确结论

```powershell
python scripts\check_wechat_draft.py
# 第一行：DRAFT_API_UNAVAILABLE
# 之后：完整信封 JSON（reason / errcode / fallback / creds_source）
```

输出第一行永远是 `DRAFT_API_AVAILABLE` 或 `DRAFT_API_UNAVAILABLE`，便于脚本 `grep`；
后续 JSON 是统一信封，便于未来 Router 按字段消费。

### 交付物 4：两套 Session / 工作区隔离，工具面不交叉

| 维度 | quant | writing |
|---|---|---|
| profile | `~/.dsh/profiles/quant` | `~/.dsh/profiles/writing` |
| 工作区 | `C:\AI_workspace\stock_agent_manager` | `C:\AI_workspace\wechat_writing` |
| MCP 服务端 | `srq`（7 个量化工具） | `draft`（3 个草稿/合规工具） |
| shell / subagent / web | 均关闭 | 均关闭 |
| 实测工具总数 | 15（6 个 `mcp__srq__*` + 文件工具） | 12（3 个 `mcp__draft__*` + 文件工具） |
| 实测 | `CALL mcp__srq__list_experiments` 成功 | `CALL mcp__draft__wechat_probe_draft` 成功，`NO_SRQ_TOOL` |

证据：[`dsh_quant_tool_call.jsonl`](../output/evidence/dsh_quant_tool_call.jsonl)、
[`dsh_writing_no_quant_tool.jsonl`](../output/evidence/dsh_writing_no_quant_tool.jsonl)、
[`dsh_draft_tool_surface.jsonl`](../output/evidence/dsh_draft_tool_surface.jsonl)。

隔离的边界要说清楚：这是**工具面 + 工作区**隔离，不是操作系统级沙箱隔离。
写作会话已经没有 shell，所以无法再通过命令行触达量化代码；但它的 `write` 仍可写工作区内任意文件。
要做硬隔离，需要给 profile 配 sandbox 目录白名单，或在 Phase 2 把写作工作区做成独立目录树。

---

## 3. 一键复现

```powershell
python tools\gen_sample_data.py     # 重建数据快照（可选，已提交）
python -m unittest discover -s tests -t .   # 当前 215 项
python scripts\acceptance.py        # 当前 14 项（含知乎导出/发布台）
```

当前结果：**215/215 单测通过，14/14 验收通过**。
机器可读结果：[`output/reports/acceptance.json`](../output/reports/acceptance.json)。

---

## 4. 已知限制（不粉饰）

1. **数据是合成的**。40 个标的、1565 个交易日、62600 行，由 `tools/gen_sample_data.py`
   固定种子生成。它内部埋了动量/价值/质量的弱信号，所以回测"看起来有东西"是设计使然，
   不能作为任何真实结论。
2. **没有接真实 SolidRockQuant**。`srq-compat` 只覆盖简报列出的 6 个工具，字段名按简报约定
   自定；真实产品的字段未必一致，接上时需要做一次字段映射。
3. **`draft/add` 未验证**。没有凭据，无法回答"你的订阅号到底能不能写草稿"。
4. **`dsh headless` 不支持 preset**（源码硬限制），所以 Phase 1 的隔离落在 profile 层；
   preset 版本配置已就绪但只在 Web 表面生效。
5. **合规扫描是正则 + 否定窗口**，不是语义审核。反讽、长分句否定可能漏判，
   所以草稿一律 `status: draft`，发布永远需要人来点。
6. **成本模型单一**：单边换手 × 固定 bps，没有滑点、没有冲击成本、没有流动性约束。

---

## 5. Phase 2 预留

- **Router**：`agents/envelope.py` 已经给出统一信封，派活规则应写成
  `kind + status + handoff_eligible` 的硬编码表，而不是提示词里的"请你判断是否……"。
- **数据接入**：替换 `quant/data.py::load_panel`，`data_version` 语义不变。
- **部署验证**：`run_paper_session` 已具备模拟盘台账能力，接真实行情后可直接复用。
- **不做的**：常驻调度、自主派活、实盘、自动发布——Phase 1 到 Phase 3 都不碰。
