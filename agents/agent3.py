"""Agent 3：公众号文章草稿生成（最高到草稿箱或 Markdown 文件）。

硬边界（简报第 3、7 节）：
- 没有发布能力：本模块不 import 任何 freepublish 调用，也没有发布函数。
- 没有量化工具：不 import quant 包，拿不到 run_backtest。
- 合规扫描不通过时拒绝产出，写入 output/rejected/ 供人复查。

两条路径输出同一套信封，便于 Phase 2 的 Router 按固定字段消费。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.envelope import envelope, rel, utc_now, write_json  # noqa: E402
from writing import article as art  # noqa: E402
from writing.drafts import DraftRejected, DraftUnavailable, create_draft  # noqa: E402
from writing.wechat import WeChatError, probe_draft_api  # noqa: E402

AGENT = "agent3-wechat-writing"


def _save_markdown(markdown: str, filename: str) -> str:
    os.makedirs(art.ARTICLE_DIR, exist_ok=True)
    path = os.path.join(art.ARTICLE_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)
    os.replace(tmp, path)
    return path


def _save_rejected(markdown: str, filename: str) -> str:
    d = os.path.join(ROOT, "output", "rejected")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)
    return path


def run(brief: dict, channel: str = "auto", thumb_media_id: str | None = None) -> dict:
    rendered = art.render(brief)
    compliance = rendered["compliance"]

    if not compliance["ok"]:
        path = _save_rejected(rendered["markdown"], rendered["filename"])
        return envelope(
            agent=AGENT,
            kind="article.draft",
            status="blocked",
            id_="blocked-" + utc_now().replace(":", ""),
            summary={
                "stage": "compliance_gate",
                "violations": compliance["violations"],
                "name_channel_hits": compliance["name_channel_hits"],
                "title": brief.get("title"),
            },
            artifacts=[
                {"type": "rejected_markdown", "path": rel(path), "channel": "file", "media_id": None}
            ],
            compliance={"checked": True, "ok": False, "violations": compliance["violations"]},
            error="合规扫描未通过，拒绝写入正式文章目录",
        )

    chosen = channel
    reason = ""
    if channel == "auto":
        probe = probe_draft_api()
        if probe["available"] and thumb_media_id:
            chosen = "wechat-draft"
            reason = "草稿接口可用且提供了封面素材 ID"
        elif probe["available"] and not thumb_media_id:
            chosen = "markdown"
            reason = "草稿接口可用，但缺少 thumb_media_id（草稿必须有封面素材），降级为 Markdown"
        else:
            chosen = "markdown"
            reason = f"草稿接口不可用：{probe['reason']} — {probe['detail']}"

    if chosen == "wechat-draft":
        try:
            created = create_draft(
                title=brief["title"],
                markdown=rendered["markdown"],
                author=brief.get("author"),
                digest=brief.get("summary", ""),
                tags=brief.get("tags"),
                data_source=str(rendered["front_matter"].get("data_source") or "synthetic"),
                thumb_media_id=thumb_media_id,
            )
        except DraftUnavailable as exc:
            # 显式要求写草稿但接口不可用时不静默降级，交给调用方决定
            return envelope(
                agent=AGENT,
                kind="article.draft",
                status="blocked",
                id_="draft-unavailable-" + utc_now().replace(":", ""),
                summary={
                    "stage": "wechat_draft_unavailable",
                    "reason": exc.probe.get("reason"),
                    "detail": exc.probe.get("detail"),
                    "fallback": "markdown",
                },
                compliance={"checked": True, "ok": True, "violations": [], "published": False},
                error=str(exc),
            )
        media_id = created["media_id"]
        return envelope(
            agent=AGENT,
            kind="article.draft",
            status="ok",
            id_=media_id,
            summary={
                "stage": "wechat_draft_created",
                "title": brief["title"],
                "slug": rendered["slug"],
                "word_count": rendered["word_count"],
                "channel": "wechat_draft",
                "media_id": media_id,
                "decision_reason": reason or "显式指定 wechat-draft",
                "published": False,
            },
            artifacts=[
                {"type": "wechat_draft", "path": None, "channel": "wechat_draft", "media_id": media_id}
            ],
            compliance={
                "checked": True,
                "ok": True,
                "violations": [],
                "disclaimer_version": compliance["disclaimer_version"],
                "published": False,
                "publish_api": "absent",
            },
        )

    path = _save_markdown(rendered["markdown"], rendered["filename"])
    return envelope(
        agent=AGENT,
        kind="article.draft",
        status="ok",
        id_=rendered["slug"],
        summary={
            "stage": "markdown_written",
            "title": brief["title"],
            "slug": rendered["slug"],
            "date": rendered["date"],
            "word_count": rendered["word_count"],
            "channel": "markdown",
            "media_id": None,
            "decision_reason": reason or "显式指定 markdown",
            "experiment_ref": rendered["front_matter"]["experiment_ref"],
            "published": False,
        },
        artifacts=[
            {
                "type": "markdown_article",
                "path": rel(path),
                "channel": "file",
                "media_id": None,
                "front_matter": rendered["front_matter"],
            }
        ],
        compliance={
            "checked": True,
            "ok": True,
            "violations": [],
            "disclaimer_version": compliance["disclaimer_version"],
            "published": False,
            "publish_api": "absent",
        },
    )


def main(argv: list[str] | None = None) -> int:
    from quant.console import force_utf8

    force_utf8()
    ap = argparse.ArgumentParser(prog="agent3", description="Agent 3 生成公众号文章草稿")
    ap.add_argument("--brief", required=True, help="结构化写作简报 JSON")
    ap.add_argument("--channel", choices=["auto", "markdown", "wechat-draft"], default="auto")
    ap.add_argument("--thumb-media-id", help="草稿封面素材 ID（微信草稿必填）")
    ap.add_argument("--out", help="信封输出路径")
    args = ap.parse_args(argv)

    with open(args.brief, encoding="utf-8-sig") as fh:
        brief = json.load(fh)

    try:
        env = run(brief, args.channel, args.thumb_media_id)
    except WeChatError as exc:
        env = envelope(
            agent=AGENT,
            kind="article.draft",
            status="blocked",
            id_="wechat-error-" + utc_now().replace(":", ""),
            summary={"stage": "wechat_draft_failed", "errcode": exc.errcode, "errmsg": exc.errmsg},
            compliance={"checked": True, "ok": True, "violations": [], "published": False},
            error=str(exc),
        )

    if args.out:
        write_json(args.out, env)
        env["written_to"] = rel(args.out)
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0 if env["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
