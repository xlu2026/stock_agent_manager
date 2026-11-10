r"""把一篇已完成的 Markdown 文章推进公众号草稿箱。

    python scripts/push_draft.py --file C:\AI_workspace\wechat_writing\articles\2026-11-07-opening.md --dry-run
    python scripts/push_draft.py --file C:\AI_workspace\wechat_writing\articles\2026-11-07-opening.md --thumb-media-id <素材ID>

边界：只调 draft/add，写进草稿箱就停。**没有 freepublish，也没有任何发布函数**——
发布必须由人在公众号后台手动点击。

前置条件（缺一样都推不进去）：
1. `WECHAT_APPID` / `WECHAT_APPSECRET`（微信开发者平台「我的业务 → 公众号 → 基础信息 → 开发密钥」，
   AppID 形如 wx…，不是 gh_ 开头的原始 ID）；
2. 调用方出口 IP 已加入同一页的 API IP 白名单；
3. 一个永久图片素材的 `thumb_media_id`（草稿的封面，draft/add 必填）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agents.envelope import utc_now, write_json  # noqa: E402
from quant.console import force_utf8  # noqa: E402
from writing.compliance import article_compliance  # noqa: E402
from writing.drafts import DraftRejected, DraftUnavailable, create_draft  # noqa: E402
from writing.wechat import load_credentials, probe_draft_api  # noqa: E402

REPORTS = os.path.join(ROOT, "output", "reports")


def split_front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.startswith(" ") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("["):
            try:
                meta[key] = json.loads(value)
            except json.JSONDecodeError:
                meta[key] = value
        elif value.startswith('"') and value.endswith('"'):
            meta[key] = value[1:-1]
        elif value in ("null", "~"):
            meta[key] = None
        else:
            meta[key] = value
    return meta, text[m.end() :]


def preflight(meta: dict, body: str, thumb: str | None) -> dict:
    """把"为什么推不进去"一次说清楚，而不是让用户撞三次墙。"""
    creds = load_credentials()
    probe = probe_draft_api() if creds["present"] else {"available": False, "reason": "NO_CREDENTIALS", "detail": "未配置凭据"}
    compliance = article_compliance(
        str(meta.get("title") or ""), body, meta.get("tags") or [], data_source=str(meta.get("data_source") or "synthetic")
    )
    return {
        "file_ok": bool(meta.get("title")),
        "title": meta.get("title"),
        "compliance_ok": compliance["ok"],
        "violations": compliance["violations"],
        "warnings": compliance["warnings"],
        "credentials_present": creds["present"],
        "appid_masked": creds["appid_masked"],
        "api_available": probe["available"],
        "api_reason": probe.get("reason"),
        "api_detail": probe.get("detail"),
        "thumb_media_id": thumb or None,
        "thumb_present": bool(thumb),
        "blockers": [
            b
            for b in (
                None if meta.get("title") else "文章缺少 title",
                None if compliance["ok"] else f"合规未通过：{[v['rule'] for v in compliance['violations']]}",
                None if creds["present"] else "缺少 WECHAT_APPID / WECHAT_APPSECRET",
                None if probe["available"] else f"草稿接口不可用：{probe.get('reason')}",
                None if thumb else "缺少 thumb_media_id（草稿封面素材）",
            )
            if b
        ],
    }


def _slug_of(meta: dict, path: str) -> str:
    return str(meta.get("slug") or os.path.splitext(os.path.basename(path))[0])


def _commit_workspace(title: str) -> dict:
    """推送成功后提交工作区；失败只返回原因，不影响推送结果。"""
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "commit_articles.py"), "-m", f"推送草稿：{title}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        return {"ok": proc.returncode == 0, "detail": (proc.stdout or "").strip()[-300:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "detail": str(exc)}


def _record_push(meta: dict, path: str, media_id: str, thumb: str | None, mode: str, compliance: dict) -> None:
    """写账本 + 落一份合规结果；失败不影响推送本身。"""
    try:
        from writing import ledger as draft_ledger
    except Exception:  # pragma: no cover - 账本坏了不该拦住推送
        return
    slug = _slug_of(meta, path)
    try:
        draft_ledger.append(
            {
                "slug": slug,
                "title": str(meta.get("title") or ""),
                "category": meta.get("category"),
                "media_id": media_id,
                "thumb_media_id": thumb,
                "mode": mode,
                "source_file": os.path.relpath(path, ROOT).replace("\\", "/"),
                "compliance_ok": bool(compliance.get("ok")),
            }
        )
        draft_ledger.record_compliance(slug, compliance)
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="把 Markdown 文章推送到公众号草稿箱（仅草稿，无发布）")
    ap.add_argument("--file", required=True, help="带 front matter 的 Markdown 文章")
    ap.add_argument("--thumb-media-id", default=os.environ.get("WECHAT_THUMB_MEDIA_ID"))
    ap.add_argument("--category", help="按栏目从 covers/manifest.json 取封面素材，省得手抄 media_id")
    ap.add_argument("--cover", help="封面图片路径；会自动上传为永久素材并用作 thumb_media_id")
    ap.add_argument("--update-media-id", help="已有草稿的 media_id：原地更新封面/正文，不新建草稿")
    ap.add_argument("--dry-run", action="store_true", help="只做前置检查，不调接口")
    ap.add_argument("--export-html", help="另存一份微信排版 HTML，供后台手动粘贴")
    ap.add_argument("--commit", action="store_true", help="推送成功后在工作区 git 提交一次")
    ap.add_argument("--out", help="结果信封输出路径")
    args = ap.parse_args(argv)

    path = args.file if os.path.isabs(args.file) else os.path.join(ROOT, args.file)
    if not os.path.exists(path):
        print(json.dumps({"ok": False, "error": f"文件不存在：{args.file}"}, ensure_ascii=False, indent=2))
        return 2

    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    meta, body = split_front_matter(text)

    # --category：从栏目封面清单取素材，避免在命令里贴 64 位 media_id
    if args.category and not args.thumb_media_id:
        manifest_path = os.path.join(ROOT, "output", "articles", "covers", "manifest.json")
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"封面清单读不到：{exc}"}, ensure_ascii=False, indent=2))
            return 2
        thumb = (manifest.get(args.category) or {}).get("wide")
        if not thumb:
            print(
                json.dumps(
                    {"ok": False, "error": f"栏目「{args.category}」还没有封面素材，先用 --cover 上传一次"},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        args.thumb_media_id = thumb

    # --cover：上传封面 -> 拿到 media_id；失败就在这里停，不写半截草稿
    if args.cover and not args.thumb_media_id:
        from writing.wechat import WeChatError, upload_permanent_image

        cover_path = args.cover if os.path.isabs(args.cover) else os.path.join(ROOT, args.cover)
        try:
            material = upload_permanent_image(cover_path)
        except WeChatError as exc:
            print(
                json.dumps(
                    {"ok": False, "stage": "cover_upload", "errcode": exc.errcode, "detail": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 4
        args.thumb_media_id = material["media_id"]
        print(f"封面已上传：media_id={material['media_id']}", file=sys.stderr)

    pre = preflight(meta, body, args.thumb_media_id)

    if args.export_html:
        from writing.wechat import markdown_to_wechat_html

        out_path = args.export_html if os.path.isabs(args.export_html) else os.path.join(ROOT, args.export_html)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(markdown_to_wechat_html(body))
        pre["html_exported"] = os.path.relpath(out_path, ROOT).replace("\\", "/")

    if args.dry_run:
        print(json.dumps({"ok": not pre["blockers"], "mode": "dry-run", "preflight": pre}, ensure_ascii=False, indent=2))
        return 0 if not pre["blockers"] else 3

    if args.update_media_id:
        # 整篇覆盖：原创声明、赞赏、文中广告都是编辑器里的手动设置，会被冲掉
        print(
            "警告：draft/update 是整篇覆盖，会冲掉编辑器里手动设置的原创声明、赞赏与广告位。"
            "更新后需要回后台重新勾选。",
            file=sys.stderr,
        )
        from writing.wechat import (
            WeChatError,
            get_access_token,
            load_credentials,
            markdown_to_wechat_html,
            update_draft,
        )

        if not pre["compliance_ok"]:
            print(json.dumps({"ok": False, "stage": "compliance", "violations": pre["violations"]}, ensure_ascii=False, indent=2))
            return 2
        creds = load_credentials()
        try:
            token = get_access_token(creds["appid"], creds["appsecret"])
            update_draft(
                token,
                args.update_media_id,
                {
                    "title": str(meta.get("title") or ""),
                    "author": meta.get("author") or "杂灵根散修",
                    "digest": str(meta.get("summary") or "")[:120],
                    "content": markdown_to_wechat_html(body),
                    "content_source_url": "",
                    "thumb_media_id": args.thumb_media_id or "",
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                },
            )
        except WeChatError as exc:
            print(
                json.dumps({"ok": False, "stage": "update", "errcode": exc.errcode, "detail": str(exc)}, ensure_ascii=False, indent=2)
            )
            return 5
        env = {
            "schema": "nerve.envelope/v1",
            "agent": "agent3-wechat-writing",
            "kind": "article.draft",
            "status": "ok",
            "id": args.update_media_id,
            "created_utc": utc_now(),
            "summary": {
                "stage": "wechat_draft_updated",
                "title": meta.get("title"),
                "media_id": args.update_media_id,
                "thumb_media_id": args.thumb_media_id,
                "channel": "wechat_draft",
                "published": False,
                "source_file": os.path.relpath(path, ROOT).replace("\\", "/"),
            },
            "compliance": {"checked": True, "ok": True, "violations": [], "published": False, "publish_api": "absent"},
        }
        out = args.out or os.path.join(REPORTS, "push_draft_latest.json")
        write_json(out, env)
        _record_push(meta, path, args.update_media_id, args.thumb_media_id, "updated", env["compliance"])
        if args.commit:
            env["commit"] = _commit_workspace(str(meta.get("title") or ""))
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return 0

    try:
        result = create_draft(
            title=str(meta.get("title") or ""),
            markdown=body,
            author=meta.get("author"),
            digest=str(meta.get("summary") or ""),
            tags=meta.get("tags") or [],
            thumb_media_id=args.thumb_media_id,
            data_source=str(meta.get("data_source") or "synthetic"),
        )
    except DraftRejected as exc:
        print(json.dumps({"ok": False, "stage": "compliance", "violations": exc.compliance["violations"]}, ensure_ascii=False, indent=2))
        return 2
    except DraftUnavailable as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "api", "reason": exc.probe.get("reason"), "detail": exc.probe.get("detail"), "preflight": pre},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3

    env = {
        "schema": "nerve.envelope/v1",
        "agent": "agent3-wechat-writing",
        "kind": "article.draft",
        "status": "ok",
        "id": result["media_id"],
        "created_utc": utc_now(),
        "summary": {
            "stage": "wechat_draft_created",
            "title": meta.get("title"),
            "media_id": result["media_id"],
            "channel": "wechat_draft",
            "published": False,
            "source_file": os.path.relpath(path, ROOT).replace("\\", "/"),
            "warnings": pre["warnings"],
        },
        "compliance": {**result["compliance"], "published": False, "publish_api": "absent"},
    }
    out = args.out or os.path.join(REPORTS, "push_draft_latest.json")
    write_json(out, env)
    _record_push(meta, path, result["media_id"], args.thumb_media_id, "created", env["compliance"])
    if args.commit:
        env["commit"] = _commit_workspace(str(meta.get("title") or ""))
    print(json.dumps(env, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
