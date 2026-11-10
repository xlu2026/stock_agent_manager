"""平台导出 CLI：把 canonical 文章转成平台可粘贴稿。

    python -m writing.export C:\\AI_workspace\\wechat_writing\\articles\\2026-11-07-opening.md
    python -m writing.export --all

边界：只读文章、只写导出文件；不联网、不读平台凭据、不发布。
导出物默认落仓库 output/articles/zhihu/；成文稿在写作工作区。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from .article import ARTICLE_DIR
from .platforms.zhihu import ExportError, ExportRejected, export_article

PLATFORMS = {"zhihu": export_article}


def _force_utf8() -> None:
    """Windows 控制台默认 GBK；这里不 import quant，自己把输出流改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _all_articles() -> list[str]:
    return sorted(glob.glob(os.path.join(ARTICLE_DIR, "*.md")))


def _dedup(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        key = os.path.abspath(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="writing.export",
        description="把文章导出为平台可粘贴稿（不发布）",
    )
    parser.add_argument("articles", nargs="*", help="文章 Markdown 路径")
    parser.add_argument("--platform", choices=sorted(PLATFORMS), default="zhihu")
    parser.add_argument("--all", action="store_true", help="导出写作工作区 articles 下的全部文章")
    parser.add_argument("--out-dir", help="输出目录（默认 output/articles/zhihu）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = parser.parse_args(argv)

    paths = list(args.articles)
    if args.all:
        paths.extend(_all_articles())
    paths = _dedup(paths)
    if not paths:
        parser.error("请给出文章路径，或使用 --all")

    exporter = PLATFORMS[args.platform]
    rc = 0
    for path in paths:
        try:
            result = exporter(path, out_dir=args.out_dir)
        except ExportRejected as exc:
            print(f"拒绝导出：{path}")
            print(json.dumps(exc.compliance, ensure_ascii=False, indent=2))
            rc = 2
            continue
        except (ExportError, OSError) as exc:
            print(f"导出失败：{path}：{exc}")
            rc = 2
            continue

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            continue
        print(f"导出：{os.path.relpath(result['html_path'], os.getcwd())}")
        for step in result["checklist"]:
            print("  " + step)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
