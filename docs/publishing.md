# 发布台（Publishing Desk）

> 一条命令看状态，一张卡片照着发，一条命令回填。**不发布、不碰浏览器、不读平台凭据。**

## 1. 三个命令

```powershell
# 看所有文章在微信/知乎的状态
python scripts\publish.py status
python scripts\publish.py status --markdown   # 贴文档用
python scripts\publish.py status --json       # 给脚本用

# 生成知乎导出 + 发布卡片（可选顺便推微信草稿）
python scripts\publish.py prepare agent-approval-002
python scripts\publish.py prepare agent-approval-002 --platform zhihu
python scripts\publish.py prepare agent-approval-002 --push-wechat

# 人工发布后回填
python scripts\publish.py done --platform zhihu agent-approval-002 --url https://zhuanlan.zhihu.com/p/...
python scripts\publish.py done --platform wechat agent-approval-002
```

`prepare` 不会发布；`done` 只改本地记录，也不会发布。

## 2. status 怎么读

| 列 | 含义 |
|---|---|
| 微信 | `已发布 <日期>` / `草稿（已推）` / `草稿（未推）` |
| 知乎 | `已发布` / `已导出` / `导出过期` / `未导出` |
| 下一步 | 按顺序要做的动作 |

常见下一步：

- `推微信草稿`：还没进草稿箱
- `发布微信`：草稿已在，去后台勾选项并发布
- `导出知乎` / `重导知乎`：没导出，或源文正文改过
- `发布知乎`：导出是新的，去知乎粘贴发布
- `回填知乎 URL`：已发布但没登记链接
- `改稿（合规未过）`：先过 `writing/compliance.py`，再谈发布

“导出过期”只认正文变化；只改 front matter 的 `status` / `published_at` 不会误报。

## 3. 发布卡片

`prepare` 会在 `output/reports/publish_cards/<slug>.md` 生成一张卡片，包含：

- 标题、栏目、源文件、合规结果
- 微信：是否已推草稿、要勾的原创/AI 声明/合集
- 知乎：正文 HTML、兜底 MD、元数据、专栏、封面、话题
- 两边的发布清单
- 发布后要跑的回填命令

照着卡片勾，不需要翻 JSON 或回忆上次怎么发的。

## 4. 默认选项

`config/publishing.json` 放“一次决定、以后复用”的默认值：

```json
{
  "wechat": {
    "original": true,
    "ai_declaration": "AI辅助创作",
    "album_by_category": {"量化研究": "量化研究", "AI技术": "AI技术"}
  },
  "zhihu": {
    "column": "杂灵根散修录",
    "ai_declaration": "AI辅助创作"
  }
}
```

原创/AI 声明仍然由人勾；配置只是把“该勾什么”提前写清楚。

## 5. 两条清单

### 微信

1. `prepare --push-wechat` 或 `push_draft.py --category` 推草稿
2. 后台预览
3. 勾原创 / AI 声明 / 合集（按卡片）
4. 手动发布
5. `publish.py done --platform wechat <slug>`

### 知乎

1. `prepare <slug>` 生成 HTML + meta
2. 知乎写文章 → 选专栏
3. 粘 HTML、传封面、勾话题、勾 AI 声明
4. 确认文末 `本文首发于公众号「杂灵根散修录」`
5. 手动发布
6. `publish.py done --platform zhihu <slug> --url <URL>`

## 6. 边界

- **没有浏览器自动化**：不登录、不点发布、不碰 cookie。
- **没有发布接口**：不调用 `freepublish`，不调知乎写接口。
- **不存凭据**：`config/publishing.json` 只放选项，不放密码/token。
- 发布、原创声明、AI 声明永远由人完成。

## 7. 建议节奏

- 写作日：只写，不发布
- 发布日：`status` → `prepare` 一批 → 照卡片发 → `done` 回填
- 每篇的“完成”定义：合规通过、导出未过期、封面/话题齐、URL 已回填

这样不用每天重新想“发到哪了、还差什么”。
