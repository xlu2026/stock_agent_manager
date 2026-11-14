r"""给文章文件名加 `[分类_编号]` 前缀，顺序取自正文副标题里的编号。

    python scripts\rename_articles.py --dry-run
    python scripts\rename_articles.py

只改文件名，不动内容；已经是 `[分类_编号]` 前缀的会跳过。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing.article import ARTICLE_DIR  # noqa: E402

SUBTITLE_RE = re.compile(r"^\*[^*·]+·\s*([^\s*]+)\s*(\d+)\*\s*$", re.M)
PREFIX_RE = re.compile(r"^\[[^\]]+\]\s")


def read_meta(path: str) -> tuple[str, str | None, str | None]:
    text = open(path, encoding="utf-8").read()
    category = None
    for line in text.splitlines():
        if line.startswith("category:"):
            category = line.split(":", 1)[1].strip().strip('"')
            break
    m = SUBTITLE_RE.search(text)
    if m:
        return text, category or m.group(1), m.group(2)
    return text, category, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="给文章加 [分类_编号] 前缀")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    plan = []
    for path in sorted(glob.glob(os.path.join(ARTICLE_DIR, "*.md"))):
        name = os.path.basename(path)
        if PREFIX_RE.match(name):
            continue
        _, category, number = read_meta(path)
        if category and number:
            prefix = f"[{category}_{number}]"
        else:
            prefix = "[存档]"
        plan.append((path, prefix, name))

    for path, prefix, name in plan:
        target = os.path.join(os.path.dirname(path), f"{prefix} {name}")
        print(f"{name}  ->  {os.path.basename(target)}")
        if not args.dry_run:
            os.rename(path, target)

    print(json.dumps({"ok": True, "renamed": len(plan), "dry_run": args.dry_run}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
