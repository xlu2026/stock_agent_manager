# 公众号账号状态与运维记录

这张表记录这个号"现在能不能做什么"，避免过几周又忘了上次卡在哪一步。
每次账号状态变化（开通、授权、封禁、改配置）都在文末的变更记录里追加一行。

> 本文件不含任何密钥。AppSecret 只存在于本地 `.env`（已被 `.gitignore` 忽略）。

## 1. 账号基本信息

| 项 | 值 |
|---|---|
| 公众号名称 | 杂灵根散修录 |
| AppID | `wx0e04fdba2871bad4` |
| 原始 ID | `gh_96c386e9ff35`（仅用于二维码/跳转，不能调接口） |
| 主体 | 个人 |
| 定位 | 认知记录：把价值判断写成可回测的因子，记录过程与失败 |
| 公众号简介 | 一个散户的公开笔记本：把判断写成可回测的因子，记录过程与失败。（31 字含标点，2026-11-08 定稿，上限 120 字） |

## 2. 开发接口状态

| 能力 | 状态 | 证据 / 说明 |
|---|---|---|
| 服务端 API（token） | ✅ 可用 | `cgi-bin/token` 正常返回 |
| access_token 复用 | ⬜ **未缓存** | 每次现取、不落盘；有效期 7200 秒（`expires_in`），重复获取会让上一张失效（40001 `not latest`） |
| 草稿箱 `draft/add` | ✅ **有权限** | 探测返回 `40007 invalid media_id`——权限通、占位 ID 被拒属预期 |
| 草稿箱 `draft/get` / `draft/update` | ✅ 可用 | 已用于原地更换草稿封面 |
| 发布 `freepublish` | ❌ 刻意不接 | 代码库无该调用；发布永远人工（开篇已于 2026-11-08 人工发布） |
| API IP 白名单 | ✅ 已配置 | 当前出口 IP `171.223.68.xxx`（**动态**，换网/重播会变） |

**IP 白名单失效的表现**：`40164 invalid ip ... not in whitelist`，微信会在 errmsg 里回显它看到的 IP，
直接照着加即可。这是配置问题，不是权限问题，别和 `48001` 混为一谈。

**重置 AppSecret 的连锁反应**：一个号只有一个 AppSecret，重置即失效，所有在用的脚本同时断。
顺序是：先确认新值往哪写（`.env`）→ 重置 → 取一次 token 确认 → 再跑推草稿。

**凭据在哪拿（2026-07 起入口已迁移）**：后台 `设置与开发 → 开发接口管理` 只剩一句迁移提示和一个链接，
真正的入口是[微信开发者平台](https://developers.weixin.qq.com/platform/) →「我的业务」→ 公众号 →「基础信息」：
AppID 在页面开头，「开发密钥」里是 AppSecret（启用 / 重置）和 API IP 白名单。
平台**不保存** AppSecret，忘了只能重置——这也是它必须落在 `.env` 里的原因。

## 3. 变现状态

| 项目 | 状态 | 说明 |
|---|---|---|
| 广告收入（流量主） | ⏳ **未满足开通条件** | 后台原话：「你暂未满足开通条件，可预约开通广告收入功能」 |
| 预约开通 | ✅ 已于 2026-11-07 点击 | 满足条件后自动开通/提醒；不影响发文 |
| 文中广告 | ❌ 暂不可用 | 流量主未开通，编辑器无广告按钮；且 OpenAPI 本身不支持插广告 |
| 文末广告 | ❌ 暂不可用 | 同上 |
| 金融类广告屏蔽 | ⬜ 待办 | 开通后再设置：行业屏蔽（金融大类）+ 广告主屏蔽（点名） |
| 赞赏（账户） | ✅ 已开通 | 收款走微信零钱，档位在「收入变现 → 赞赏」配置 |
| 赞赏（单篇） | ⬜ 待勾 | **只能手动**：编辑器里先声明原创，再选赞赏账户；OpenAPI 无此字段 |
| 带货 / 微信小店 | ⬜ 不适用 | 需要商品与资质 |

## 3.5 手动设置与脚本的冲突（重要）

原创声明、赞赏、文中广告、AI 声明，这四样**都不在 OpenAPI 字段里**，只能在编辑器里手动设置。
而 `draft/update` 是**整篇覆盖**——重推一次，这些手动设置会连同正文一起被冲掉。

所以固定成这个顺序，别反过来：

```
改 Markdown → push_draft.py 推正文 → 后台勾原创 / 赞赏 / AI 声明 / 广告 → 发布
```

反过来（先勾再推）等于白勾。**要改一篇已经勾过原创的草稿，必须预留"重勾一次"的时间。**

脚本只能提醒"这次是整篇覆盖"，做不到"只改正文、保留手动设置"——微信没有提供局部更新的接口。

## 3.6 AI 声明（2025-09 起要求，且只能手动）

- **规则**：《人工智能生成合成内容标识办法》2025-09-01 施行；微信同日公告要求，用户发布 AI 生成合成内容时
  需**主动声明**，平台也会对"疑似 AI"的内容加提示。平台加的标识不得删除、篡改或隐匿。
- **接口**：`draft/add` 的请求参数表里**没有** AI 声明字段（2026-11 核对）。所以这事和原创、赞赏同类，
  只能进编辑器手动勾。
- **本号的固定披露句**（放正文开头，逐字）：

  > 本文由我口述、AI 协助整理，观点与判断由我负责。

  口述整理稿在 front matter 标 `ai_assisted: true`，`article_compliance(..., ai_assisted=True)` 会校验这句，
  缺句直接判违规（常量见 `writing/compliance.py::AI_DISCLOSURE`）。
  这类稿子的 `generated_by` 写 `oral-dictation+ai-edit`、`render_path` 写 `manual-markdown`，方便日后分清来源。
  已发布稿在 front matter 用 `ai_declared` 记录当时勾了什么（例：开篇 `ai_declared: "AI创作"`）。
- **两层要分开做**：正文里对读者说清楚（披露句），编辑器里对平台勾清楚（AI 声明）。只做一样都不算完。
- **已发生的一例**：开篇（2026-11-08 发布）发布时标注了「AI 创作」；那一篇正文里没有披露句——
  这条规矩是之后才定的，从 AI技术 001（原 002）起补齐。

## 4. 已产出资产

| 资产 | media_id / 路径 |
|---|---|
| 开篇（**已发布**） | 媒体 ID `oQ7ed1ezuToxNUiewgDQh7UBaz4yHVXJ3gcUGNhfcqpi-WURFCwgmY0aNKZ6mSUu`；2026-11-08 人工发布，发布时标注「AI 创作」 |
| 开篇封面（2.35:1） | `oQ7ed1ezuToxNUiewgDQhzBQ3sghms-F67YLxPYgPfTtFNQwpN0ZQzr6HJimJT2d` |
| 001（**已在草稿箱**，原归档后重新启用） | 草稿 media_id `oQ7ed1ezuToxNUiewgDQh3S1QzJ9sqosrtcPws9jmn4WxZkw8RGqAUsQFhwxs6-P`；封面素材 `oQ7ed1ezuToxNUiewgDQhziRTwCvzzDMs8zLyeuE_jyA-dBRkbdaGyXZ58ZBTtl6`（源 `covers/cover-quant-2.35x1.png`）；源文件 `C:\AI_workspace\wechat_writing\articles\2026-11-08-factor-to-backtest-001.md`（brief 已标 `status: draft`、`category: 量化研究`） |
| 量化研究 002（**已在草稿箱**） | 草稿 media_id `oQ7ed1ezuToxNUiewgDQhzTyRJrUcdsg9nDfZlJH8uz7904NjlGzwNVdagLnbmip`；封面沿用 `covers/cover-quant-2.35x1.png`（素材同上）；源文件 `C:\AI_workspace\wechat_writing\articles\` 下同名文件 |
| 量化研究 003（**已在草稿箱**） | 草稿 media_id `oQ7ed1ezuToxNUiewgDQhwKUBp61hUk2EV5HZf-DDfdrXrK7bZtfEnAw7i0uCgCQ`；封面沿用 `covers/cover-quant-2.35x1.png`（素材同上）；源文件 `C:\AI_workspace\wechat_writing\articles\` 下同名文件 |
| AI技术 002（**已在草稿箱**） | 草稿 media_id `oQ7ed1ezuToxNUiewgDQh-9_AhBJHlDal1hBZoSsmL0wIXxkts4-TzQxAhdsf_FD`；封面沿用 `covers/cover-ai-2.35x1.png`（素材同上）；源文件 `C:\AI_workspace\wechat_writing\articles\` 下同名文件 |
| AI技术 001（原开发日志 002，**已发布**） | 草稿 media_id `oQ7ed1ezuToxNUiewgDQhwTDo2stSy2m8M1cvkHj1lgY7VRVhRZZBqVuiGiRLDa_`（发布后已移出草稿箱）；封面素材 `oQ7ed1ezuToxNUiewgDQh1si_VbZa5a7HXKGqJKVQW4L32Jo38nl9zp9WnMB-pba`（源 `covers/cover-ai-2.35x1.png`）；源文件 `C:\AI_workspace\wechat_writing\articles\2026-11-08-agent-to-draftbox-001.md` |
| 封面源文件 | `output/articles/cover-opening-2.35x1.png`、`cover-opening-1x1.png` |
| 栏目封面（4 组） | `output/articles/covers/cover-{quant,ai,market,misc}-{2.35x1,1x1}.png`（见 `docs/article-categories.md`） |
| HTML 备份 | `output/articles/2026-11-07-opening.wechat.html` |

本表是给人看的摘要；草稿位置以 `output/reports/drafts.jsonl` 账本为准（每次推送追加一行）。

`status` 取值：`draft`（待发）/ `published`（已发布，配 `published_at`）/ `archived`（暂不使用）。
发布稿另有 `ai_declared` 记录发布时勾了什么。开篇与 001 的 front matter 已按此更新。

## 5. 待办

- [ ] **重置 AppSecret**：密钥曾出现在对话记录中，发布完这篇后去开发者平台重置，并更新 `.env`（先确认 `.env` 可写再重置）。
- [ ] **access_token 加缓存**：7200 秒有效，提前 5 分钟刷新；当前每次现取。
- [ ] **量化研究 001**：已入草稿箱（2026-11-08）。剩：编辑器勾「原创」「AI 声明」→ 选合集「量化研究」→ 发布。
- [ ] **量化研究 002 / 003**：已入草稿箱。同上，勾「原创」「AI 声明」，合集「量化研究」。
- [ ] **AI技术 002**：已入草稿箱。勾「原创」「AI 声明」，合集「AI技术」。
- [ ] 在后台确认封面在列表卡片里的裁切效果（头图中间区域最安全）。
- [ ] 流量主开通后：设置行业屏蔽（金融大类）+ 广告主屏蔽（点名校验）。

## 6. 变更记录

| 日期 | 事件 |
|---|---|
| 2026-11-07 | 首次确认草稿箱接口**有权限**（40007 探测通过） |
| 2026-11-07 | IP 白名单加入 `171.223.68.xxx`，此前报 `40164` |
| 2026-11-07 | 修复探测逻辑 bug：HTTP 200 + body.errmsg 的错误曾被误判为"可用" |
| 2026-11-07 | 开篇草稿写入草稿箱，随后原地更新为正式封面 |
| 2026-11-07 | 广告收入功能**未满足开通条件**，已点「预约开通」 |
| 2026-11-07 | 赞赏账户已开通（单篇设置待手动勾） |
| 2026-11-07 | 合成数据声明由「本文回测」改为「前期回测」，源文件与线上草稿已同步 |
| 2026-11-08 | 开发日志 002 定稿（本地），固定 AI 披露句进入正文，front matter 标 `ai_assisted: true` |
| 2026-11-08 | 核对 `draft/add` 参数表：无 AI 声明字段，改为编辑器手动勾（写入 §3.6） |
| 2026-11-08 | 合规闸门新增 `ai_assisted` 校验：标了就必须逐字含披露句，缺句判违规 |
| 2026-11-08 | **开篇已人工发布**，发布时标注「AI 创作」；该篇正文无披露句（规矩在其后定） |
| 2026-11-08 | **001 归档**：brief 标 `status: archived`，渲染产物同步；暂不使用、不推送 |
| 2026-11-08 | 001 去重：删掉 11-07 旧副本，归档只留一份渲染产物 |
| 2026-11-08 | 栏目定为四类（量化研究 / AI技术 / 市场复盘 / 杂项），规则见 `docs/article-categories.md`；开篇归杂项、002 归 AI技术 |
| 2026-11-08 | 修正取密钥路径：入口已迁至微信开发者平台（我的业务 → 公众号 → 基础信息 → 开发密钥），旧写法「设置与开发 → 基本配置」作废；002 与 `push_draft.py` 前置说明同步 |
| 2026-11-08 | 生成四个栏目的封面（2.35:1 + 1:1），脚本 `tools/make_category_covers.ps1` |
| 2026-11-08 | 开发日志 002 写入草稿箱（media_id `oQ7ed1ez…GiRLDa_`），封面用 `covers/cover-ai-2.35x1.png`（素材 `oQ7ed1ez…nMB-pba`）；**未发布**，待勾「原创」「AI 声明」 |
| 2026-11-08 | 副标题改为与栏目挂钩，编号按栏目各自计算：002 重编为 `AI技术 001`（文件改名 `2026-11-08-agent-to-draftbox-001.md`，slug `agent-to-draftbox-001`），001 → `量化研究 001`，开篇 → `杂项 001`；草稿箱里那篇的正文随后重推覆盖 |
| 2026-11-08 | 量化研究 001 重写后重新启用（`archived` → `draft`）：去掉「不是/而是」与情绪化表述、补引擎实测数字、改实盘口径；写入草稿箱（media_id `oQ7ed1ez…xs6-P`），封面 `covers/cover-quant-2.35x1.png`（素材 `oQ7ed1ez…Btl6`） |
| 2026-11-08 | 新增三篇并写入草稿箱：量化研究 002（因子由谁选）、量化研究 003（交易终端怎么选）、AI技术 002（下单为什么卡在人工批准）；封面复用已传素材，未重复上传 |
| 2026-11-08 | AI技术 001 已发布（2026-11-08）；发布后草稿移出草稿箱，正文与封面 media_id 保留作历史记录 |
| 2026-11-08 | 公众号简介定稿：「一个散户的公开笔记本：把判断写成可回测的因子，记录过程与失败。」（31 字含标点） |
| 2026-11-09 | 量化研究 001 补「四个因子分别是什么」一节（1123 字），原地覆盖草稿（media_id 不变）；覆盖会清掉已勾的手动设置 |
| 2026-11-09 | 修复草稿 HTML 转义顺序 bug：块内换行先写 `<br/>` 再 `html.escape`，导致后台显示字面量；改为先转义再插 `<br/>`，量化研究 001 已重推 |
| 2026-11-09 | 文末改为「实验 ID」「风险提示」各自成段（不再用 `<br/>` 连接），规避编辑器把自闭合标签显示成字面量；001 再推一次 |
| 2026-11-09 | 主会话成文的三篇（量化研究 002/003、AI技术 002）移到 `C:\AI_workspace\wechat_writing\articles\`；仓库 `output/articles/` 只留 001（重渲染产物）与开篇（已发布） |
