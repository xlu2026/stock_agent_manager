"""把结构化写作简报渲染成带 front matter 的 Markdown。

确定性渲染：同样的简报 + 同样的日期 => 同样的字节。这让"草稿"可复现、可 diff，
也让未来的 Router 能按固定字段消费，而不必解析自然语言。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from .compliance import (
    DISCLAIMER_VERSION,
    RISK_DISCLAIMER,
    SYNTHETIC_NOTICE,
    article_compliance,
)

ARTICLE_SCHEMA = "nerve.article/v1"
CST = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 成文稿统一放写作工作区（Agent 3 的目录），仓库不再保留文章副本。
# 验收时用 WFR_ARTICLES_DIR 把落盘目录临时指到报告目录。
WECHAT_WORKSPACE = os.environ.get("WECHAT_WORKSPACE") or r"C:\AI_workspace\wechat_writing"
ARTICLE_DIR = os.environ.get("WFR_ARTICLES_DIR") or os.path.join(WECHAT_WORKSPACE, "articles")

# 栏目只有这四类，定义与归属见 docs/article-categories.md。
# 认不出的值一律落回 `杂项`，不猜它属于哪一类；未指定栏目同样落 `杂项`。
CATEGORIES = ("量化研究", "AI技术", "市场复盘", "杂项")
DEFAULT_CATEGORY = "杂项"

REQUIRED = ("title", "summary", "sections")


class BriefError(ValueError):
    pass


def _yaml_scalar(value) -> str:
    """极简 YAML 标量输出：字符串一律双引号，避免中文/冒号/井号引起歧义。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _yaml_block(key: str, value, indent: int = 0) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        lines.append(f"{pad}{key}:")
        for k, v in value.items():
            lines.extend(_yaml_block(k, v, indent + 2))
    elif isinstance(value, (list, tuple)):
        if not value:
            lines.append(f"{pad}{key}: []")
        else:
            lines.append(f"{pad}{key}:")
            for item in value:
                lines.append(f"{pad}  - {_yaml_scalar(item)}")
    else:
        lines.append(f"{pad}{key}: {_yaml_scalar(value)}")
    return lines


def slugify(title: str) -> str:
    """中文标题无法直接转写，用稳定哈希保证 slug 唯一且可复现。"""
    import hashlib

    ascii_part = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if ascii_part and len(ascii_part) >= 4:
        return ascii_part[:48]
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
    return f"article-{digest}"


def word_count(text: str) -> int:
    """中文按字计，英文按词计——公众号编辑口径的近似。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z0-9_'\-]*", re.sub(r"[\u4e00-\u9fff]", " ", text)))
    return cjk + latin


def update_front_matter(path: str, updates: dict[str, str]) -> dict:
    """就地改写 front matter 里的若干字段，正文原样保留。

    只做行级替换，不引入 YAML 依赖：已有 key 换行，缺的 key 补在闭合 `---` 之前。
    返回 {key: 新值}，便于调用方回显。
    """
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    if not text.startswith("---\n"):
        raise ValueError(f"不是带 front matter 的文章：{path}")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise ValueError(f"front matter 没有闭合：{path}")

    lines = text[:end].split("\n")  # 首行是 ---
    tail = text[end:]  # 从闭合 --- 开始

    done: set[str] = set()
    for i, line in enumerate(lines):
        for key, value in updates.items():
            if line.startswith(f"{key}:"):
                lines[i] = f'{key}: "{value}"'
                done.add(key)

    missing = [k for k in updates if k not in done]
    if missing:
        for key in missing:
            lines.append(f'{key}: "{updates[key]}"')

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + tail)
    return {k: updates[k] for k in updates}


def validate_brief(brief: dict) -> dict:
    if not isinstance(brief, dict):
        raise BriefError("简报必须是 JSON 对象")
    missing = [k for k in REQUIRED if k not in brief]
    if missing:
        raise BriefError(f"简报缺少字段 {missing}")
    if not isinstance(brief["sections"], list) or not brief["sections"]:
        raise BriefError("sections 必须是非空数组")
    for i, sec in enumerate(brief["sections"]):
        if not isinstance(sec, dict) or "heading" not in sec or "body" not in sec:
            raise BriefError(f"sections[{i}] 需要 heading 与 body")
        if not isinstance(sec["body"], list):
            raise BriefError(f"sections[{i}].body 必须是段落数组")
    if not str(brief["title"]).strip():
        raise BriefError("title 不能为空")
    return brief


def render(brief: dict, *, now: datetime | None = None, experiment_ref: str | None = None) -> dict:
    """渲染文章，返回 {markdown, meta, compliance}。"""
    brief = validate_brief(brief)
    now = now or datetime.now(CST)
    # 简报可以钉住日期：文章日期应跟着首发日走，不随渲染当天漂移。
    date_str = str(brief.get("date") or now.astimezone(CST).strftime("%Y-%m-%d"))

    slug = brief.get("slug") or slugify(str(brief["title"]))
    tags = list(brief.get("tags") or [])
    series = brief.get("series") or "杂灵根散修录"
    author = brief.get("author") or "杂灵根散修"
    raw_category = brief.get("category") or DEFAULT_CATEGORY
    category = raw_category if raw_category in CATEGORIES else DEFAULT_CATEGORY
    phase = brief.get("phase") or "phase-1"
    exp_ref = experiment_ref or brief.get("experiment_ref")

    lines: list[str] = []
    lines.append(f"# {brief['title']}")
    lines.append("")
    if brief.get("subtitle"):
        lines.append(f"*{brief['subtitle']}*")
        lines.append("")
    lines.append(f"> {brief['summary']}")
    lines.append("")

    for sec in brief["sections"]:
        lines.append(f"## {sec['heading']}")
        lines.append("")
        for para in sec["body"]:
            lines.append(str(para).rstrip())
            lines.append("")

    data_source = str(brief.get("data_source") or "synthetic")
    # "none"：纯工程/方法文章，不含任何回测数字，不需要合成数据声明。
    if data_source not in ("real", "none"):
        lines.append(SYNTHETIC_NOTICE)
        lines.append("")

    if brief.get("footnote"):
        lines.append(str(brief["footnote"]).rstrip())
        lines.append("")

    lines.append("---")
    lines.append("")
    if exp_ref:
        lines.append(f"实验 ID：{exp_ref}")
        lines.append("")
    lines.append(f"风险提示：{RISK_DISCLAIMER}")
    lines.append("")
    body = "\n".join(lines).rstrip() + "\n"

    body_words = word_count(body)
    compliance = article_compliance(str(brief["title"]), body, tags, data_source=data_source)

    front = {
        "schema": ARTICLE_SCHEMA,
        "title": brief["title"],
        "slug": slug,
        "date": date_str,
        "status": brief.get("status") or "draft",
        "author": author,
        "series": series,
        "category": category,
        "phase": phase,
        "tags": tags,
        "summary": brief["summary"],
        "experiment_ref": exp_ref,
        "data_source": data_source,
        "word_count": body_words,
        "compliance": {
            "checked": True,
            "ok": compliance["ok"],
            "disclaimer_version": DISCLAIMER_VERSION,
            "violation_count": len(compliance["violations"]),
            "warnings": compliance["warnings"],
        },
        "generated_by": "agent3-writing",
        "render_path": "degraded-markdown",
    }

    fm: list[str] = ["---"]
    for k, v in front.items():
        fm.extend(_yaml_block(k, v))
    fm.append("---")
    fm.append("")

    markdown = "\n".join(fm) + "\n" + body
    return {
        "markdown": markdown,
        "slug": slug,
        "date": date_str,
        "filename": f"{date_str}-{slug}.md",
        "word_count": body_words,
        "front_matter": front,
        "compliance": compliance,
    }
