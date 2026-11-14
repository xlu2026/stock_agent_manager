# Agent 1 / 2 / 3 架构审查（2026-11-11）

审查范围：`agents/`、`quant/mcp_server.py`、`quant/instruction.py`、`quant/data_mcp.py`、
`quant/data_jobs.py`、`cordis/prompts/*.md`、`cordis/profiles/*.yml`、`tools/build_cordis.py`、
`tools/install_dsh_profile.py`、`scripts/acceptance.py`，以及实际跑过的三个 profile 会话。

## 1. 现状

| | Agent 1（quant） | Agent 2（agent2） | Agent 3（writing） |
|---|---|---|---|
| 角色 | 研究指令 → 回测 → 实验 | 刷新/体检数据快照 | 素材 → 公众号草稿 |
| 入口 | `dsh --profile quant` / `scripts/run_agent1.py` | `dsh --profile agent2` | `dsh --profile writing` |
| MCP | `srq`（11 工具） | `data`（4 工具） | `draft`（3 工具） |
| 写盘 | `experiments/`、`output/reports/` | `output/data_jobs/`、快照目录 | 工作区 `articles/` |
| shell | 关 | 关 | 关 |
| 工作区 | 仓库 | 仓库 | 约定为 `wechat_writing`，**未强制** |

编码方式：Agent 2 是"profile + MCP 服务端"，没有 `agents/agent2.py`；Agent 1 同时有 Python
编排（`agents/agent1.py`）和 MCP 直调两条路；Agent 3 的 LLM 在 profile 里，`agents/agent3.py`
只是确定性渲染器。

## 1.1 修复状态（2026-11-11）

| 项 | 状态 | 落点 |
|---|---|---|
| P0-1 因子选择未被代码强制 | ✅ 已修 | `srq --toolset research` 只暴露 9 个工具，隐藏 `run_backtest` / `validate_strategy` |
| P0-2 `run_research_instruction` 跳过校验 | ✅ 已修 | `_tool_research` 先 `validate_strategy`，失败返回 `ok=false`，不登记实验 |
| P0-3 Agent 1 提示词过期/矛盾 | ✅ 已修 | `cordis/prompts/agent1.md` 重写（合成/真实两种模式、新工具清单、条件限定语） |
| P1-4 `SPEC_SCHEMA.universe` 硬编码 | ✅ 已修 | enum 从 `UNIVERSE_ALIASES` 生成 |
| P1-5 失败信封不落盘 | ✅ 已修 | `agents/agent1.py::_finish`，所有返回路径都写 `out_path` |
| P1-6 "已是最新"误报体检失败 | ✅ 已修 | `data_jobs` 无 manifest 时标 `no_new_snapshot`，不再跑体检 |
| P1-7 Agent 2 配置靠 shell 环境 | ✅ 已修 | `config/agent2.json`（环境变量优先），`list_snapshots` 返回配置状态 |
| P1-8 写作工作区隔离 | ⚠️ 部分 | workspaceRoot 已固定；实测 fs 工具仍可越界读写，需 OS 层隔离 |
| P2-13 没有最新快照指针 | ✅ 已修 | 刷新成功写 `output/data/latest.json`；Agent 1 加 `--latest` |
| P2-14 实验记录含个股代码 | ✅ 已修 | 公开记录持仓脱敏；代码在 `experiments/.private/`（gitignore），新增 `get_experiment_holdings` |
| P2-9 `McpClient` 不排空 stderr | ✅ 已修 | 独立 drain 线程保留尾部 200 行 |
| P2-10 空目录无法重试 | ✅ 已修 | 只按“文件”判空 |
| P2-11 Agent 2 无取消/超时 | ✅ 已修 | `cancel_job` + `timeout_seconds`（杀进程树） |
| P2-18 作业目录无清理 | ✅ 已修 | `cleanup_jobs`（keep/dry_run，running 不删） |
| P2-19 `dv` 只覆盖 prices.csv | ⏳ 未做 | `manifest.sha256` 目前等于 prices 哈希；calendar/universe 变化不改变 dv（2026-11-12 实测两份不同快照同 dv） |
| P2-12 参数校验不足 | ✅ 已修 | `end/start` 格式、out_dir 必须在快照根下、sample/index/timeout 校验；`end<=base.end` 直接 noop |
| P2-15 双入口 contract 不一致 | ✅ 已修 | Python 入口改为直接调 `run_research_instruction`，contract 由服务端统一生成 |
| P2-16 `looks_like_internal_spec` 后门 | ✅ 已修 | 只有显式 `--internal-spec` 才接受原始 spec |
| P2-17 验收不查提示词/工具面 | ✅ 已修 | 新增第 11、12 项：提示词一致性、研究模式工具面 + 校验先于登记 |

## 2. 缺陷（按严重度）

### P0-1 因子选择在 MCP 工具面上没有被代码强制

`quant/mcp_server.py:32` 的 `SPEC_SCHEMA` 直接暴露 `factor` 枚举，而 `run_backtest`、
`validate_strategy`、`run_factor_analysis`、`run_paper_session` 都接受 `spec`（`mcp_server.py:55-76`）。
Agent 1 的 LLM 可以绕开 `run_research_instruction` 的关键词映射，自己传 `factor`。
"模型不能自选因子"目前只是提示词约定，不是代码保证——与 README/验收的声明不一致。

修法：给 MCP 服务端加工具集开关（如 `SRQ_TOOLSET=research`），Agent 1 profile 只暴露
`run_research_instruction` / `run_factor_analysis` / `run_paper_session` / broker 工具；
`run_backtest` / `validate_strategy` 只留给 Python 编排和测试。

### P0-2 `run_research_instruction` 跳过 `validate_strategy`

`_tool_research`（`mcp_server.py:79`）直接 `_run_spec`（`:93`），没有预热/区间/数据版本校验。
Python 路径（`agents/agent1.py:88`）会先 validate，LLM 路径不会——2020-01-02 只有 244 天预热
那个问题，在 LLM 路径上会被直接放行并登记成实验。

修法：`_tool_research` 内先 `validate_strategy(spec)`，失败返回结构化错误，不写实验记录。
更彻底：把"校验 + 运行 + 登记"收成一个 `run_spec_checked()`，三条入口共用。

### P0-3 Agent 1 系统提示词已过期，且自相矛盾

`cordis/prompts/agent1.md`：

- `:5-7` 说 universe 只支持 `synthetic_40`；实际已支持 `沪深300`/`hs300_40_pit`。
- `:19`、`:34` 说"数据是合成样本，不是真实行情"，并要求结尾必须这么写；真实快照下这是错的。
- `:3` 说"唯一该调用的入口是 run_research_instruction"，但 `:25` 又让调
  `run_factor_analysis` / `run_paper_session`。
- `:17` 说"当前没有任何下单工具"，但工具面里确有 `broker_propose_order` / `broker_submit_order`，
  `:38-59` 又教怎么用。

修法：按"数据模式（合成/真实）+ 工具清单"重写；结尾限定语改成按 `data_source` 条件生成；
明确"raw spec 工具不可用"（配合 P0-1）。

### P1-4 `SPEC_SCHEMA.universe` 硬编码 `synthetic_40`

`mcp_server.py:36` 的 `enum: ["synthetic_40"]`。真实池名不在 schema 里，LLM 看到枚举会以为
只能跑合成；而 Python 路径绕过 schema 直接传 `hs300_40_pit`，两条路的能力描述不一致。

修法：enum 改为从 `UNIVERSE_ALIASES` 的值生成，或去掉 enum 改为描述。

### P1-5 Agent 1 拒绝路径不落盘

`agents/agent1.py:159` 只在成功时 `write_json`；校验失败、MCP 工具错误都直接 return。
`scripts/run_agent1.py` 只把信封打到 stdout，没有文件。失败实验无法追溯。

修法：`_rejected` 之后也写 `out_path`（或由 `run_agent1.py` 统一写）。

### P1-6 Agent 2"已是最新"被误报成体检失败

导出脚本在 `--end <= base 末尾` 时打印"已是最新"并 `return 0`（`export_baostock_snapshot.py:419`），
但没写 manifest。`data_jobs`（`:71-90`）看到退出码 0 就断言成功，接着跑体检，
`manifest.exists` 失败 → `state=failed`、`error="快照体检未通过"`。
Agent 2 会报告"体检失败"，而真实原因是"没有新数据"。

修法：`data_jobs` 在 `ok` 但无 manifest 时置 `failed` + `error="没有生成新快照（已是最新或区间无新交易日）"`；
或让导出脚本在这种情况返回非 0 并带明确信息。

### P1-7 Agent 2 配置只靠 shell 环境变量

`quant/data_mcp.py` 的 `NFR_BAOSTOCK_PYTHON` / `NFR_SNAPSHOT_ROOT` / `NFR_EXPORT_SCRIPT` /
`NFR_DATA_JOB_DIR` 都从环境读。从 GUI 或未设变量的终端启动 `dsh --profile agent2`，
第一次 `refresh_snapshot` 就会失败；提示词里也没写怎么设。

修法（按可行性排序）：
1. 若 `dsh-mcp-client` 支持 `env` 配置，在 `agent2.yml` 里写死默认值；
2. 加 `config/agent2.json`（repo 内、机器相关项 gitignore），MCP 启动时读；
3. 至少让 `list_snapshots` 在缺变量时返回明确的"未配置"提示，而不是等刷新才报错。

### P1-8 写作工作区无法靠 profile 强制（已实测，结论修正）

原先的判断是"workspaceRoot 没钉住"。2026-11-11 已给三份 profile 都钉了 `sandbox-policy.workspaceRoot`
（writing = `C:/AI_workspace/wechat_writing`，quant/agent2 = 仓库），`--dump-config` 确认生效。

但实测结果：

- writing 会话（从仓库 cwd 启动）仍能 `read` `C:\AI_workspace\stock_agent_manager\experiments\index.jsonl`；
- 也能 `write` `C:\AI_workspace\stock_agent_manager\output\_probe_write.txt`。

原因不是配置没生效，而是 **`dsh-tool-fs` 的文件读写不经过 sandbox 的路径限制**；
`sandbox-policy.workspaceRoot` 只约束 shell 沙箱，而 writing profile 已关闭 shell。

结论：**profile 层做不了路径级读写隔离**。真正的隔离只能靠 OS 层（独立 Windows 用户 + ACL
拒绝其读仓库）或独立机器；或者做数据最小化——从 `experiments/*.json` 的 `holdings.names`
里去掉个股代码（只留 `count`/`turnover`），把个股明细另存到受控目录。

钉住 `workspaceRoot` 仍然保留：语义正确，且将来 DSH 若把 fs 工具纳入沙箱会直接生效；
但文档不能据此声称"Agent 3 看不到仓库"。

### P2-9 `McpClient` 不排空 stderr

`agents/mcp_client.py:31-40` 用 `stderr=PIPE`，运行期间从不读；服务端日志超过管道缓冲（约 64KB）
就会阻塞。目前服务端日志少，属于潜在死锁。

修法：`stderr=subprocess.DEVNULL`，或起一个 drain 线程保留尾部。

### P2-10 Agent 2 空目录无法原地重试

`quant/data_mcp.py:161` 用 `os.listdir(out_dir)` 判非空；失败后留下的空子目录会让重试被拒，
只能不断新建 `_r2/_r3`。修法：用 `walk` 判"是否有文件"，全空则允许复用。

### P2-11 Agent 2 没有取消/超时

`refresh_snapshot` 启的是 detached 进程，`data_jobs` 无限等待；baostock 挂起时作业会一直
`running`，只能人工杀进程。修法：加 `cancel_job`（按 pid 杀进程树）和可选 `timeout_seconds`。

### P2-12 Agent 2 参数校验不足

`refresh_snapshot` 不校验 `end` 格式、不限制 `out_dir` 必须在 `NFR_SNAPSHOT_ROOT` 之下、
不校验 `index/sample` 组合。错误会推迟到导出脚本，反馈慢。修法：入口处校验并给可读错误。

### P2-13 没有"最新快照"指针

Agent 2 成功后只返回 dv/目录；Agent 1 仍要人工传 `--data-dir`，示例指令还 pin 了旧
`dv-632cc7c31340`。修法：Agent 2 写 `output/data/latest.json`（dv/dir/end/created_at），
Agent 1 加 `--latest`，示例不再 pin 死版本。

### P2-14 Agent 3 提示词有一处过期

`cordis/prompts/agent3.md:123` 写"当前数据快照就是合成样本"；真实数据下这句话不成立。
应改成"当 data_source=synthetic 时"，与实际校验逻辑一致。

### P2-15 双入口语义可能漂移

Python 入口（`agents/agent1.py`）与 MCP 入口（`run_research_instruction`）各自组装 contract：
前者有 `resolved`，后者没有；前者先 validate，后者不 validate。修法：统一由服务端一个函数
生成 contract，两入口只传参。

### P2-16 `looks_like_internal_spec` 给 Python 入口留了后门

`agents/agent1.py:54` 收到带 `factor` 的 dict 就当内部 spec 直接跑，绕过四字段契约。
用于诊断可以，但应显式加 `--internal-spec` 开关，默认拒绝。

### P2-17 验收没有覆盖提示词/工具面一致性

现有验收检查了 profile 漂移和工具面隔离，但没有检查：
- Agent 1 提示词是否还把数据说成合成；
- Agent 1 LLM 工具面是否暴露了 `run_backtest`；
- Agent 2 缺环境变量时是否有可读错误。
建议把这三条加进 `scripts/acceptance.py`。

### P2-18 作业目录与失败目录无清理

`output/data_jobs/` 只增不减；失败的快照目录要人工删。修法：保留最近 N 个，或在
`refresh_status` 里提供 `cleanup`（先确认无文件）。

## 3. 做得好的地方

- 引擎确定性、`nav_hash`、实验指纹，三条链路一致；
- profile 由提示词生成，验收检查漂移；
- Agent 2 的后台作业模型（detached + status.json）在 MCP 退出后仍能续跑；
- Agent 2 的 `wait_seconds` + `today` 已经解决了第一轮暴露的轮询和命名问题；
- 工具面隔离（srq/draft/data 三套）方向正确，只是 Agent 1 内部还需要再切一刀。

## 4. 建议修复顺序

1. **P0-2 + P0-1**：`run_research_instruction` 加校验；工具集收窄。这是"模型不能自选因子"的底线。
2. **P0-3 + P1-4**：重写 Agent 1 提示词和 SPEC_SCHEMA 的 universe 描述。
3. **P1-5 + P1-6**：失败信封落盘；"已是最新"不再误报体检失败。
4. **P1-7 + P1-8**：Agent 2 配置内置；写作工作区固定。
5. P2 里优先 P2-10（重试）、P2-11（取消）、P2-13（latest 指针），其余按需。

## 5. 2026-11-11 工作区固定实测记录

改动：`tools/build_cordis.py` 给三份 profile 生成 `sandbox-policy` patch，固定
`workspaceRoot`；`config` 是整体替换，所以三个字段（mode / workspaceRoot /
additionalWritableRoots）都抄全了。`--dump-config` 输出：

- quant → `C:/AI_workspace/stock_agent_manager`
- writing → `C:/AI_workspace/wechat_writing`
- agent2 → `C:/AI_workspace/stock_agent_manager`

实测（从仓库 cwd 启动 `dsh --profile writing`）：

| 动作 | 结果 |
|---|---|
| 读 `experiments/index.jsonl` | 成功，返回第一行 |
| 写 `output/_probe_write.txt` | 成功，文件已创建（探针已删） |

因此结论修正为：该固定只对 shell 沙箱生效，**不能**阻止 fs 工具读写工作区之外的路径。
