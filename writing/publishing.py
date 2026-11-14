"""发布台：跨平台状态聚合、发布卡片与回填。

这一层只读写本地文件，不发布、不碰浏览器、不读平台凭据：
- `scan()` 汇总微信（front matter + drafts 账本）与知乎（sidecar）的状态；
- `prepare()` 生成知乎导出与一张发布卡片；
- `done_*()` 只回填“已发布”记录，发布动作仍由人完成。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .article import ARTICLE_DIR, CATEGORIES, update_front_matter
from .compliance import article_compliance
from .ledger import latest_by_slug, read_all
from .platforms import zhihu

CST = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZHIHU_DIR = Path(zhihu.DEFAULT_OUT_DIR)
DEFAULT_CARD_DIR = PROJECT_ROOT / "output" / "reports" / "publish_cards"
DEFAULT_CHANGELOG = Path(ARTICLE_DIR).parent / "CHANGELOG.md"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "publishing.json"

DEFAULT_CONFIG = {
    "wechat": {
        "original": True,
        "ai_declaration": "AI辅助创作",
        "album_by_category": {category: category for category in CATEGORIES},
        "reward": False,
    },
    "zhihu": {
        "column": "杂灵根散修录",
        "ai_declaration": "AI辅助创作",
        "topics_by_category": copy.deepcopy(zhihu.TOPIC_MAP),
    },
}

ZHIHU_URL_RE = re.compile(r"^https?://zhuanlan\.zhihu\.com/p/\d+/?$")


class PublishError(ValueError):
    """发布台的前置条件不满足。"""


def load_config(path: str | os.PathLike | None = None) -> dict:
    """读取发布默认值；文件不存在时用内置默认值。"""
    config = copy.deepcopy(DEFAULT_CONFIG)
    target = Path(path) if path else DEFAULT_CONFIG_PATH
    if not target.exists():
        return config
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return config
    for section in ("wechat", "zhihu"):
        if isinstance(raw.get(section), dict):
            config[section].update(raw[section])
    return config


def resolve_article(target: str | os.PathLike, article_dir: str | os.PathLike | None = None) -> Path:
    """支持 slug 片段或完整路径。"""
    direct = Path(target)
    if direct.exists() and direct.suffix.lower() == ".md":
        return direct
    base = Path(article_dir or ARTICLE_DIR)
    hits = sorted(base.glob(f"*{target}*.md"))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise PublishError(f"找不到文章：{target}")
    raise PublishError("匹配到多篇，请写得更具体：" + "、".join(p.name for p in hits))


def _read_article(path: Path) -> tuple[str, dict, str]:
    text = path.read_text(encoding="utf-8-sig")
    front, body = zhihu.parse_front_matter(text)
    return text, front, body


def _date_of(front: dict, path: Path) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(front.get("date") or ""))
    if match:
        return match.group(1)
    match = re.match(r"(\d{4}-\d{2}-\d{2})-", path.name)
    return match.group(1) if match else ""


def _sidecar_for(slug: str, zhihu_dir: Path) -> Path | None:
    matches = sorted(Path(zhihu_dir).glob(f"*-{slug}.zhihu.json"))
    return matches[-1] if matches else None


def _body_hash(body: str) -> str:
    return hashlib.sha256(zhihu.compose_body(body).encode("utf-8")).hexdigest()


def _is_stale(sidecar: Path, meta: dict, body: str, source_text: str) -> bool:
    """源文正文变过才算过期；只改 front matter 的 status/published_at 不算。"""
    body_hash = _body_hash(body)
    if meta.get("body_sha256"):
        return meta["body_sha256"] != body_hash
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if meta.get("source_sha256") == source_hash:
        return False
    html_path = sidecar.with_suffix(".html")
    if html_path.exists():
        expected = zhihu.markdown_to_html(zhihu.compose_body(body)).strip()
        actual = html_path.read_text(encoding="utf-8").strip()
        return expected != actual
    return True


def _compliance(front: dict, body: str) -> dict:
    return article_compliance(
        str(front.get("title") or ""),
        body,
        front.get("tags") or [],
        data_source=str(front.get("data_source") or "synthetic"),
        ai_assisted=bool(front.get("ai_assisted")),
    )


def scan(
    *,
    article_dir: str | os.PathLike | None = None,
    zhihu_dir: str | os.PathLike | None = None,
    ledger_path: str | os.PathLike | None = None,
    config: dict | None = None,
) -> dict:
    """只读聚合。返回 {articles: [...], summary: {...}}。"""
    config = config or load_config()
    base = Path(article_dir or ARTICLE_DIR)
    zh_dir = Path(zhihu_dir or DEFAULT_ZHIHU_DIR)
    drafts = latest_by_slug(read_all(ledger_path))

    rows: list[dict] = []
    skipped = 0
    for path in sorted(base.glob("*.md")):
        text, front, body = _read_article(path)
        title = str(front.get("title") or "").strip()
        slug = str(front.get("slug") or path.stem)
        category = str(front.get("category") or "杂项")
        date = _date_of(front, path)
        status = str(front.get("status") or "draft")
        if path.name.startswith("[存档]") or status == "archived":
            skipped += 1
            continue
        draft = drafts.get(slug)
        compliance = _compliance(front, body)

        wechat = {
            "state": status,
            "published_at": front.get("published_at"),
            "draft_media_id": (draft or {}).get("media_id"),
            "draft_ts": (draft or {}).get("ts"),
        }
        if status == "published":
            wechat["label"] = f"已发布 {front.get('published_at') or '缺日期'}"
        elif status == "archived":
            wechat["label"] = "存档"
        elif draft:
            wechat["label"] = "草稿（已推）"
        else:
            wechat["label"] = "草稿（未推）"

        sidecar = _sidecar_for(slug, zh_dir)
        meta: dict = {}
        if sidecar:
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
        stale = bool(sidecar and meta and _is_stale(sidecar, meta, body, text))
        published = bool(meta.get("published") or meta.get("canonical") or meta.get("status") == "published")
        if not sidecar:
            zhihu_state = "未导出"
        elif stale:
            zhihu_state = "导出过期"
        elif published:
            zhihu_state = "已发布"
        else:
            zhihu_state = "已导出"

        actions: list[str] = []
        if status == "archived":
            actions.append("存档，不发布")
        else:
            if not compliance["ok"]:
                actions.append("改稿（合规未过）")
            if status == "published":
                if not front.get("published_at"):
                    actions.append("补微信发布日期")
            elif draft:
                actions.append("发布微信")
            else:
                actions.append("推微信草稿")

            if not sidecar:
                actions.append("导出知乎")
            elif stale:
                actions.append("重导知乎")
            elif published:
                if not meta.get("canonical"):
                    actions.append("回填知乎 URL")
            else:
                actions.append("发布知乎")

            if sidecar:
                if not meta.get("topics"):
                    actions.append("补知乎话题")
                cover = meta.get("cover")
                if not cover:
                    actions.append("补封面")
                elif not (PROJECT_ROOT / cover).exists() and not Path(cover).exists():
                    actions.append("补封面")
                html_path = sidecar.with_suffix(".html")
                if not html_path.exists() or zhihu.ORIGIN_LINE not in html_path.read_text(encoding="utf-8"):
                    actions.append("重导知乎（缺首发句）")

        warnings: list[str] = []
        if title and len(title) > 100:
            actions.append("缩短标题（>100 字）")
        elif title and len(title) > 20:
            warnings.append("标题 >20 字")
        if not front.get("brief_ref"):
            warnings.append("缺 brief_ref（仅提示）")
        if status == "published" and not front.get("published_at"):
            warnings.append("published 但缺 published_at")
        if sidecar and not meta.get("topics"):
            warnings.append("知乎 sidecar 缺 topics")

        rows.append(
            {
                "slug": slug,
                "title": title,
                "category": category,
                "date": date,
                "path": str(path),
                "status": status,
                "compliance_ok": compliance["ok"],
                "violations": compliance["violations"],
                "wechat": wechat,
                "zhihu": {
                    "state": zhihu_state,
                    "canonical": meta.get("canonical"),
                    "published_at": meta.get("published_at"),
                    "exported_at": meta.get("exported_at"),
                    "topics": meta.get("topics") or [],
                    "cover": meta.get("cover"),
                    "sidecar": str(sidecar) if sidecar else None,
                },
                "actions": list(dict.fromkeys(actions)),
                "warnings": warnings,
            }
        )

    rows.sort(key=lambda r: (r["date"], r["slug"]), reverse=True)
    summary = {
        "total": len(rows),
        "wechat_published": sum(1 for r in rows if r["status"] == "published"),
        "zhihu_published": sum(1 for r in rows if r["zhihu"]["state"] == "已发布"),
        "with_actions": sum(1 for r in rows if r["actions"]),
        "skipped": skipped,
    }
    return {"articles": rows, "summary": summary, "config": config}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _card(path: Path, front: dict, compliance: dict, sidecar: Path | None, draft: dict | None, config: dict) -> str:
    title = str(front.get("title") or "").strip()
    slug = str(front.get("slug") or path.stem)
    category = str(front.get("category") or "杂项")
    status = str(front.get("status") or "draft")
    wechat_cfg = config.get("wechat", {})
    zhihu_cfg = config.get("zhihu", {})

    lines = [
        f"# 发布卡片：{title}",
        "",
        f"- slug：`{slug}`",
        f"- 栏目：{category}",
        f"- 源文件：`{path}`",
        f"- 微信状态：{status}" + (f"（{front.get('published_at')}）" if front.get("published_at") else ""),
        f"- 合规：{'通过' if compliance['ok'] else '未通过'}",
        "",
        "## 微信",
    ]
    if status == "published":
        lines.append(f"- 已发布：{front.get('published_at') or '日期缺失'}，无需再推。")
    else:
        if draft:
            lines.append(f"- 草稿已在草稿箱：media_id `{draft.get('media_id')}`")
        else:
            lines.append("- 尚未推草稿。先运行：")
            lines.append("")
            lines.append(f"  `python scripts\\push_draft.py --file \"{path}\" --category \"{category}\"`")
        lines += [
            "",
            "审核时按下面勾选：",
            f"- [ ] 原创声明：{'是' if wechat_cfg.get('original', True) else '按需'}",
            f"- [ ] AI 声明：{wechat_cfg.get('ai_declaration', 'AI辅助创作')}",
            f"- [ ] 合集：{wechat_cfg.get('album_by_category', {}).get(category) or '不选'}",
        ]
        if wechat_cfg.get("reward"):
            lines.append("- [ ] 赞赏")
        lines.append("- [ ] 预览确认后手动发布")

    lines += ["", "## 知乎"]
    if not sidecar:
        lines.append("- 尚未导出。先运行 `python scripts\\publish.py prepare " + slug + "`。")
    else:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        html_path = sidecar.with_suffix(".html")
        md_path = sidecar.with_suffix(".md")
        topics = " / ".join(meta.get("topics") or []) or "手动选"
        cover = meta.get("cover") or "手动选图"
        lines += [
            f"- 正文：`{html_path}`",
            f"- 兜底：`{md_path}`",
            f"- 元数据：`{sidecar}`",
            f"- 专栏：{zhihu_cfg.get('column', '杂灵根散修录')}",
            f"- 封面：`{cover}`",
            f"- 话题：{topics}",
            "",
            "发布时按下面走：",
            "- [ ] 打开知乎 → 写文章 → 选专栏",
            f"- [ ] 标题：{title}",
            "- [ ] 粘贴正文 HTML",
            "- [ ] 上传封面",
            "- [ ] 勾话题",
            f"- [ ] AI 声明：{zhihu_cfg.get('ai_declaration', 'AI辅助创作')}",
            f"- [ ] 文末首发句：{zhihu.ORIGIN_LINE}",
            "- [ ] 预览确认后手动发布",
        ]
        if meta.get("canonical"):
            lines.append(f"- 已登记 URL：{meta['canonical']}")
        else:
            lines += [
                "",
                "发布后回填：",
                "",
                f"  `python scripts\\publish.py done --platform zhihu {slug} --url <URL>`",
            ]

    if status != "published":
        lines += [
            "",
            "微信发布后回填：",
            "",
            f"  `python scripts\\publish.py done --platform wechat {slug}`",
        ]
    lines += ["", "> 本卡片只做准备；发布、原创/AI 声明由人手动完成。", ""]
    return "\n".join(lines)


def prepare(
    target: str,
    *,
    platform: str = "all",
    article_dir: str | os.PathLike | None = None,
    zhihu_dir: str | os.PathLike | None = None,
    card_dir: str | os.PathLike | None = None,
    config: dict | None = None,
) -> dict:
    """生成知乎导出与发布卡片；不推草稿、不发布。"""
    config = config or load_config()
    path = resolve_article(target, article_dir)
    _text, front, body = _read_article(path)
    compliance = _compliance(front, body)
    if not compliance["ok"]:
        raise PublishError(f"合规未通过：{[v['rule'] for v in compliance['violations']]}")

    export = None
    if platform in ("all", "zhihu"):
        export = zhihu.export_article(str(path), out_dir=str(zhihu_dir or DEFAULT_ZHIHU_DIR))

    slug = str(front.get("slug") or path.stem)
    sidecar = _sidecar_for(slug, Path(zhihu_dir or DEFAULT_ZHIHU_DIR))
    draft = latest_by_slug(read_all()).get(slug)
    card = _card(path, front, compliance, sidecar, draft, config)
    card_path = Path(card_dir or DEFAULT_CARD_DIR) / f"{slug}.md"
    _atomic_write(card_path, card)

    return {
        "ok": True,
        "slug": slug,
        "title": front.get("title"),
        "category": front.get("category"),
        "wechat_status": front.get("status"),
        "path": str(path),
        "card": str(card_path),
        "export": export,
        "compliance": compliance,
    }


def done_zhihu(
    target: str,
    url: str,
    *,
    date: str | None = None,
    zhihu_dir: str | os.PathLike | None = None,
    force: bool = False,
) -> dict:
    if not ZHIHU_URL_RE.match(url.strip()):
        raise PublishError("知乎 URL 不合法，应为 https://zhuanlan.zhihu.com/p/<数字>")
    zh_dir = Path(zhihu_dir or DEFAULT_ZHIHU_DIR)
    slug = target
    sidecar = _sidecar_for(slug, zh_dir)
    if not sidecar:
        path = resolve_article(target)
        _text, front, _body = _read_article(path)
        slug = str(front.get("slug") or path.stem)
        sidecar = _sidecar_for(slug, zh_dir)
    if not sidecar:
        raise PublishError("找不到知乎 sidecar，先跑 prepare")

    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    current = meta.get("canonical")
    if current and current != url and not force:
        raise PublishError(f"已登记不同 URL：{current}（要覆盖加 --force）")
    published_at = date or datetime.now(CST).strftime("%Y-%m-%d")
    meta.update(
        {
            "status": "published",
            "canonical": url.strip(),
            "published_at": published_at,
            "published": True,
        }
    )
    note = f"知乎发布：{published_at}"
    notes = str(meta.get("notes") or "")
    if note not in notes:
        meta["notes"] = (notes + "；" if notes else "") + note
    _atomic_write(sidecar, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "slug": slug, "sidecar": str(sidecar), "canonical": url.strip(), "published_at": published_at}


def _append_changelog(changelog: Path, date: str, title: str, path: Path) -> None:
    if not changelog.exists():
        return
    text = changelog.read_text(encoding="utf-8")
    line = f"- {date} 发布：{title}（`{path.name}`）"
    if line in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    changelog.write_text(text + line + "\n", encoding="utf-8", newline="\n")


def done_wechat(
    target: str,
    *,
    date: str | None = None,
    article_dir: str | os.PathLike | None = None,
    changelog: str | os.PathLike | None = None,
) -> dict:
    path = resolve_article(target, article_dir)
    _text, front, _body = _read_article(path)
    title = str(front.get("title") or path.stem)
    published_at = date or datetime.now(CST).strftime("%Y-%m-%d")
    if front.get("status") == "published" and front.get("published_at") == published_at:
        return {"ok": True, "already": True, "slug": front.get("slug"), "published_at": published_at}
    update_front_matter(str(path), {"status": "published", "published_at": published_at})
    _append_changelog(Path(changelog or DEFAULT_CHANGELOG), published_at, title, path)
    return {
        "ok": True,
        "slug": front.get("slug") or path.stem,
        "title": title,
        "path": str(path),
        "published_at": published_at,
    }
