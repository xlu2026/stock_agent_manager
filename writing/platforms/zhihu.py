"""知乎导出：只做格式转换，不发布。

边界（与 AGENTS.md「对外表达」一致）：
- 不联网、不读知乎凭据、不调浏览器；
- 只产出可粘贴的稿子 + 一份人工清单；
- 发布、原创/转载声明、AI 标注都由人在知乎后台手动完成。

知乎版与公众号版的差异（详见 docs/platforms.md）：
- 去掉 YAML front matter 与正文 H1（知乎的标题是独立字段）；
- 保留刊头、导语、合成数据声明与风险提示（合规扫描要逐字命中）；
- 产出语义 HTML（h2/p/strong/blockquote/code），不照搬公众号的内联样式。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone

from ..compliance import article_compliance

PLATFORM = "zhihu"
META_SCHEMA = "nerve.platform/v1"
# 成文稿在写作工作区，导出物在仓库 output/articles/zhihu；两者不再同一个根。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUT_DIR = os.path.join(PROJECT_ROOT, "output", "articles", "zhihu")
CST = timezone(timedelta(hours=8))

MAX_TOPICS = 4
TITLE_LIMIT = 100

# 知乎版文末固定加的来源说明；源文已含这句时不重复加。
ORIGIN_LINE = "本文首发于公众号「杂灵根散修录」"
ORIGIN_MARKER = "本文首发于公众号"

# 话题只是给人工勾选的建议，最终以知乎搜索出来的话题为准。
# 刻意避开 compliance.NAME_BANNED 里的词（股票/证券/投资/理财/基金/荐股/选股/牛股/涨停/量化选股）。
TOPIC_MAP = {
    "量化研究": ["量化交易", "回测", "因子模型", "Python"],
    "AI技术": ["人工智能", "AI Agent", "编程", "软件工程"],
    "市场复盘": ["宏观经济", "金融市场", "市场分析"],
    "杂项": ["独立思考", "个人成长", "效率工具"],
}
TAG_TOPIC_MAP = {
    "方法论": "方法论",
    "回测": "回测",
    "开发日志": "编程",
    "自动化": "自动化",
    "工程": "软件工程",
}

COVER_CODES = {"量化研究": "quant", "AI技术": "ai", "市场复盘": "market", "杂项": "misc"}

# 手工回填的字段：重导出时不能被冲掉。
_MANUAL_KEYS = ("canonical", "published_at", "notes")


class ExportError(ValueError):
    """导出前置条件不满足（不是合规问题）。"""


class ExportRejected(ExportError):
    """合规闸门未通过；附带 violations 供人复查。"""

    def __init__(self, compliance: dict) -> None:
        self.compliance = compliance
        super().__init__(f"合规扫描未通过：{compliance.get('violations')}")


# --------------------------------------------------------------- front matter


_FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_H1_RE = re.compile(r"\A\s*#[ \t][^\n]*\n?", re.S)


def _scalar(text: str):
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[1:-1]
    if text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if text.startswith("[") and text.endswith("]"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    try:
        return int(text)
    except ValueError:
        return text


def parse_front_matter(markdown: str) -> tuple[dict, str]:
    """解析本项目自己生成的 YAML front matter。

    只认 `key: value`、`key:` + `- item` 列表两种形态；嵌套映射（compliance）
    整块跳过——导出不需要它，也不需要引入 PyYAML。
    """
    match = _FRONT_RE.match(markdown)
    if not match:
        return {}, markdown

    data: dict = {}
    pending: str | None = None
    for raw in match.group(1).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - "):
            if pending:
                if not isinstance(data.get(pending), list):
                    data[pending] = []
                data[pending].append(_scalar(raw[4:]))
            continue
        if raw.startswith((" ", "\t")):
            # 嵌套映射的第一行：把占位的空列表撤掉，后面同层子行继续跳过。
            if pending:
                data.pop(pending, None)
                pending = None
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = _scalar(value)
            pending = None
        else:
            data[key] = []
            pending = key

    return data, markdown[match.end() :]


def strip_h1(body: str) -> str:
    """去掉正文开头的 H1：知乎标题是独立字段，留着会重复。"""
    return _H1_RE.sub("", body, count=1).lstrip("\n")


def compose_body(body: str) -> str:
    """拼出知乎正文：去 H1、补首发句。front matter 变化不影响这个结果。"""
    text = strip_h1(body).rstrip("\n")
    if ORIGIN_MARKER not in text:
        text = f"{text}\n\n{ORIGIN_LINE}"
    return text + "\n"


# --------------------------------------------------------------- HTML


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_CODE_RE = re.compile(r"`([^`\n]+)`")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")


def _markup(escaped: str) -> str:
    """在已 HTML 转义的文本上套行内标记。"""
    out = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    out = _CODE_RE.sub(r"<code>\1</code>", out)
    out = _ITALIC_RE.sub(r"<em>\1</em>", out)
    return out


def _paragraph(text: str) -> str:
    escaped = html.escape(text, quote=False).replace("\n", "<br/>")
    return f"<p>{_markup(escaped)}</p>"


def markdown_to_html(markdown: str) -> str:
    """极简 Markdown -> 知乎可接受的语义 HTML。

    不写内联样式：知乎编辑器会剥掉 style，留着只会干扰粘贴结果。
    """
    blocks = re.split(r"\n\s*\n", markdown.strip())
    out: list[str] = []
    for block in blocks:
        text = block.strip()
        if not text:
            continue
        if re.fullmatch(r"-{3,}", text):
            out.append("<hr/>")
        elif text.startswith("### "):
            out.append(f"<h3>{_markup(html.escape(text[4:].strip(), quote=False))}</h3>")
        elif text.startswith("## "):
            out.append(f"<h2>{_markup(html.escape(text[3:].strip(), quote=False))}</h2>")
        elif text.startswith("# "):
            # 正常情况下 strip_h1 已经删掉；这里兜底，避免标题漏进正文。
            out.append(f"<h2>{_markup(html.escape(text[2:].strip(), quote=False))}</h2>")
        elif text.startswith("> "):
            lines = [ln[2:] if ln.startswith("> ") else ln.lstrip("> ") for ln in text.splitlines()]
            quoted = "\n".join(lines)
            escaped = html.escape(quoted, quote=False).replace("\n", "<br/>")
            out.append(f"<blockquote>{_markup(escaped)}</blockquote>")
        else:
            out.append(_paragraph(text))
    return "\n".join(out)


# --------------------------------------------------------------- 元数据


def pick_topics(front: dict) -> list[str]:
    topics: list[str] = []
    category = str(front.get("category") or "杂项")
    candidates = list(TOPIC_MAP.get(category, TOPIC_MAP["杂项"]))
    for tag in front.get("tags") or []:
        mapped = TAG_TOPIC_MAP.get(str(tag))
        if mapped:
            candidates.append(mapped)
    for topic in candidates:
        if topic not in topics:
            topics.append(topic)
    return topics[:MAX_TOPICS]


def cover_for(front: dict, slug: str | None = None) -> str | None:
    """单篇专用封面优先（cover-<slug>-2.35x1.png），否则用栏目封面。"""
    if slug:
        dedicated = os.path.join("output", "articles", f"cover-{slug}-2.35x1.png")
        if os.path.exists(os.path.join(PROJECT_ROOT, dedicated)):
            return dedicated
    code = COVER_CODES.get(str(front.get("category") or "杂项"), "misc")
    rel = os.path.join("output", "articles", "covers", f"cover-{code}-2.35x1.png")
    return rel if os.path.exists(os.path.join(PROJECT_ROOT, rel)) else None


def _date_of(front: dict, path: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(front.get("date") or ""))
    if match:
        return match.group(1)
    match = re.match(r"(\d{4}-\d{2}-\d{2})-", os.path.basename(path))
    if match:
        return match.group(1)
    return datetime.now(CST).strftime("%Y-%m-%d")


def _source_display(path: str) -> str:
    """仓库内的源显示相对路径；写作工作区的源保留绝对路径，避免出现 `..\\..`。"""
    path = os.path.abspath(path)
    try:
        rel = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:
        return path
    return rel if not rel.startswith("..") else path


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _merge_meta(old: dict | None, new: dict) -> dict:
    """重导出时保留人工回填的字段，不整份覆盖。"""
    if not isinstance(old, dict):
        return new
    for key in _MANUAL_KEYS:
        value = old.get(key)
        if value not in (None, ""):
            new[key] = value
    if old.get("status") == "published":
        new["status"] = "published"
        new["published"] = True
        if old.get("published_at"):
            new["published_at"] = old["published_at"]
    return new


def build_meta(
    *,
    front: dict,
    title: str,
    slug: str,
    date: str,
    topics: list[str],
    cover: str | None,
    source: str,
    source_sha256: str,
    body_sha256: str,
    compliance: dict,
) -> dict:
    return {
        "schema": META_SCHEMA,
        "platform": PLATFORM,
        "title": title,
        "slug": slug,
        "date": date,
        "series": front.get("series"),
        "category": front.get("category"),
        "summary": front.get("summary"),
        "topics": topics,
        "cover": cover,
        "source": _source_display(source),
        "source_sha256": source_sha256,
        "body_sha256": body_sha256,
        "exported_at": datetime.now(CST).isoformat(timespec="seconds"),
        "status": "exported",
        "canonical": None,
        "published_at": None,
        "published": False,
        "publish_api": "absent",
        "compliance": {
            "ok": True,
            "disclaimer_version": compliance["disclaimer_version"],
            "violations": [],
        },
    }


def build_checklist(result: dict) -> list[str]:
    meta = result["meta"]
    html_path = os.path.relpath(result["html_path"], PROJECT_ROOT)
    md_path = os.path.relpath(result["markdown_path"], PROJECT_ROOT)
    meta_path = os.path.relpath(result["meta_path"], PROJECT_ROOT)
    cover = meta.get("cover") or "手动选图"
    steps = [
        "打开知乎 → 创作中心 → 写文章（或专栏「杂灵根散修录」）",
        f"标题：{meta['title']}",
        f"正文：粘贴 {html_path} 的内容；格式丢了再改用 {md_path}",
        f"文末：已自动加首发句（{ORIGIN_LINE}）；源文已含则不重复",
        f"封面：{cover}（按编辑器提示裁）",
        f"话题：{' / '.join(meta['topics']) or '手动选'}",
        "声明：按知乎规则标注 AI 辅助创作；原创/转载按后台实际选项",
        f"发布后把 URL 回填到 {meta_path} 的 canonical，并在 docs/platforms.md 记一行",
    ]
    return [f"{i}. {step}" for i, step in enumerate(steps, 1)]


# --------------------------------------------------------------- 导出


def export_article(path: str, *, out_dir: str | None = None) -> dict:
    """把一篇 canonical 文章导出为知乎版。不联网、不发布。"""
    if not os.path.exists(path):
        raise ExportError(f"文章不存在：{path}")

    with open(path, encoding="utf-8-sig") as fh:
        markdown = fh.read()

    front, body = parse_front_matter(markdown)
    title = str(front.get("title") or "").strip()
    if not title:
        raise ExportError("front matter 缺少 title")
    if len(title) > TITLE_LIMIT:
        raise ExportError(f"标题 {len(title)} 字，超过知乎 {TITLE_LIMIT} 字上限")

    tags = [str(t) for t in (front.get("tags") or [])]
    data_source = str(front.get("data_source") or "synthetic")
    compliance = article_compliance(
        title,
        body,
        tags,
        data_source=data_source,
        ai_assisted=bool(front.get("ai_assisted")),
    )
    if not compliance["ok"]:
        raise ExportRejected(compliance)

    zhihu_markdown = compose_body(body)
    html_out = markdown_to_html(zhihu_markdown)

    date = _date_of(front, path)
    slug = str(front.get("slug") or os.path.splitext(os.path.basename(path))[0])
    base = f"{date}-{slug}"
    out_dir = out_dir or DEFAULT_OUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    html_path = os.path.join(out_dir, base + ".zhihu.html")
    markdown_path = os.path.join(out_dir, base + ".zhihu.md")
    meta_path = os.path.join(out_dir, base + ".zhihu.json")

    _write_text(html_path, html_out + "\n")
    _write_text(markdown_path, zhihu_markdown.rstrip("\n") + "\n")

    meta = build_meta(
        front=front,
        title=title,
        slug=slug,
        date=date,
        topics=pick_topics(front),
        cover=cover_for(front, slug),
        source=path,
        source_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        body_sha256=hashlib.sha256(zhihu_markdown.encode("utf-8")).hexdigest(),
        compliance=compliance,
    )
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                old = json.load(fh)
        except (OSError, json.JSONDecodeError):
            old = None
        meta = _merge_meta(old, meta)
    _write_text(meta_path, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

    result = {
        "platform": PLATFORM,
        "html_path": html_path,
        "markdown_path": markdown_path,
        "meta_path": meta_path,
        "meta": meta,
    }
    result["checklist"] = build_checklist(result)
    return result
