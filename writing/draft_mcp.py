"""写作侧的"草稿接口"：一个只有草稿能力的 MCP 服务端。

任务书要求 Agent 3「只暴露文件读写和草稿接口」，所以写作 profile 里
不注册 shell、不注册量化服务端，只挂这一个服务：

    wechat_probe_draft      探测 draft 接口是否可用（无副作用）
    wechat_add_draft        写一篇草稿，返回 media_id
    article_check_compliance 发布前合规扫描（风险提示、个股代码、荐股措辞）

这里**没有**、也不会加 ``freepublish`` 或任何发布工具：发布能力在架构上不存在，
不是"被提示词禁止"。
"""
from __future__ import annotations

import sys

from shared.mcp_stdio import McpServer

from .compliance import article_compliance
from .drafts import DraftRejected, DraftUnavailable, create_draft
from .wechat import probe_draft_api

SERVER_NAME = "wechat-draft"
SERVER_VERSION = "0.1.0"

INSTRUCTIONS = (
    "公众号草稿接口：只有草稿与合规检查能力，没有发布能力。"
    "所有工具都不会把内容推送到读者端；发布必须由人手动完成。"
)


def _tool_probe(args: dict) -> dict:
    return probe_draft_api()


def _tool_add(args: dict) -> dict:
    try:
        return create_draft(
            title=str(args.get("title", "")),
            markdown=str(args.get("markdown", "")),
            author=args.get("author"),
            digest=str(args.get("digest") or ""),
            tags=args.get("tags"),
            thumb_media_id=args.get("thumb_media_id"),
            data_source=str(args.get("data_source") or "synthetic"),
        )
    except DraftRejected as exc:
        raise ValueError(f"合规扫描未通过，拒绝写草稿：{exc.compliance['violations']}") from exc
    except DraftUnavailable as exc:
        raise RuntimeError(f"{exc}。请改为写入 Markdown 文件，不要尝试其他发布途径。") from exc


def _tool_check(args: dict) -> dict:
    return article_compliance(str(args.get("title", "")), str(args.get("markdown", "")), args.get("tags"))


TOOLS = [
    {
        "name": "wechat_probe_draft",
        "description": "探测公众号草稿接口是否可用。无副作用，不会创建草稿。返回 available/reason/detail。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_probe,
    },
    {
        "name": "wechat_add_draft",
        "description": "把一篇 Markdown 写入公众号草稿箱，返回 media_id。会先做合规扫描；不具备发布能力。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown": {"type": "string"},
                "author": {"type": "string"},
                "digest": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "thumb_media_id": {"type": "string"},
                "data_source": {"type": "string", "enum": ["synthetic", "real"]},
            },
            "required": ["title", "markdown"],
            "additionalProperties": False,
        },
        "handler": _tool_add,
    },
    {
        "name": "article_check_compliance",
        "description": "对文章做合规扫描：荐股措辞、个股代码、收益承诺，以及风险提示是否逐字存在。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "markdown": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "markdown"],
            "additionalProperties": False,
        },
        "handler": _tool_check,
    },
]


def build_server() -> McpServer:
    return McpServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
        tools=TOOLS,
    )


def serve() -> int:
    try:
        return build_server().serve()
    except WeChatError as exc:  # 只在真正调用网络时可能抛
        sys.stderr.write(f"[{SERVER_NAME}] {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(serve())
