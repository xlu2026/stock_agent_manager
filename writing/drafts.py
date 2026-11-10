"""写草稿的唯一实现。

`agents/agent3.py`（Python 入口）和 `writing/draft_mcp.py`（MCP 工具）都走这里，
避免两条路径各自拼一次 payload、各自漏一次合规检查。
"""
from __future__ import annotations

from .compliance import article_compliance
from .wechat import WeChatError, add_draft, get_access_token, load_credentials, markdown_to_wechat_html, probe_draft_api

DEFAULT_AUTHOR = "杂灵根散修"


class DraftRejected(ValueError):
    """合规闸门未通过。"""

    def __init__(self, compliance: dict) -> None:
        self.compliance = compliance
        super().__init__(f"合规扫描未通过：{compliance['violations']}")


class DraftUnavailable(RuntimeError):
    """草稿接口不可用；调用方应降级为 Markdown。"""

    def __init__(self, probe: dict) -> None:
        self.probe = probe
        super().__init__(f"草稿接口不可用（{probe['reason']}）：{probe['detail']}")


def create_draft(
    *,
    title: str,
    markdown: str,
    author: str | None = None,
    digest: str = "",
    tags: list[str] | None = None,
    thumb_media_id: str | None = None,
    data_source: str = "synthetic",
) -> dict:
    """合规 -> 探测 -> 取 token -> 写草稿。失败抛上面两种异常，不返回半成品。"""
    if not title.strip():
        raise DraftRejected({"ok": False, "violations": [{"rule": "标题为空", "matched": "", "context": ""}]})
    if not markdown.strip():
        raise DraftRejected({"ok": False, "violations": [{"rule": "正文为空", "matched": "", "context": ""}]})

    compliance = article_compliance(title, markdown, tags, data_source=data_source)
    if not compliance["ok"]:
        raise DraftRejected(compliance)

    probe = probe_draft_api()
    if not probe["available"]:
        raise DraftUnavailable(probe)

    creds = load_credentials()
    try:
        token = get_access_token(creds["appid"], creds["appsecret"])
        media_id = add_draft(
            token,
            {
                "title": title,
                "author": author or DEFAULT_AUTHOR,
                "digest": (digest or "")[:120],
                "content": markdown_to_wechat_html(markdown),
                "content_source_url": "",
                "thumb_media_id": thumb_media_id or "",
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            },
        )
    except WeChatError as exc:
        raise DraftUnavailable(
            {"reason": "API_ERROR", "detail": str(exc), "errcode": exc.errcode, "available": False}
        ) from exc

    return {
        "status": "draft_created",
        "media_id": media_id,
        "published": False,
        "publish_api": "absent",
        "compliance": {"ok": True, "violations": [], "disclaimer_version": compliance["disclaimer_version"]},
    }
