r"""把一篇草稿标记为已发布。

    python scripts\mark_published.py 2026-11-08-agent-to-draftbox-001
    python scripts\mark_published.py <路径> --date 2026-11-09 --ai-declared AI创作

做三件事：改 front matter（status/published_at，可选 ai_declared）、往工作区 CHANGELOG 追加一行、
在写作工作区提交一次 git。发布动作本身仍然由人在公众号后台点，这里只负责记账。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from writing.article import ARTICLE_DIR, update_front_matter  # noqa: E402
from quant.console import force_utf8  # noqa: E402

WORKSPACE = os.path.dirname(ARTICLE_DIR)
CHANGELOG = os.path.join(WORKSPACE, "CHANGELOG.md")
CST = timezone(timedelta(hours=8))
GIT = os.environ.get("GIT_EXE") or r"C:\AI_workspace\_tools\MinGit\cmd\git.exe"


def resolve(target: str) -> str:
    if os.path.isabs(target) and os.path.exists(target):
        return target
    if os.path.exists(target):
        return os.path.abspath(target)
    hits = glob.glob(os.path.join(ARTICLE_DIR, f"*{target}*.md"))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"找不到文章：{target}")
    raise SystemExit("匹配到多篇，请写得更具体：" + ", ".join(os.path.basename(h) for h in hits))


def title_of(path: str) -> str:
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            if line.startswith("title:"):
                return line.split(":", 1)[1].strip().strip('"')
    return os.path.splitext(os.path.basename(path))[0]


def append_changelog(date: str, title: str, path: str) -> None:
    if not os.path.exists(CHANGELOG):
        return
    with open(CHANGELOG, encoding="utf-8") as fh:
        text = fh.read()
    line = f"- {date} 发布：{title}（`{os.path.basename(path)}`）"
    if line in text:
        return
    with open(CHANGELOG, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def git_commit(paths: list[str], message: str) -> dict:
    if not os.path.exists(GIT):
        return {"ok": False, "reason": "GIT_NOT_FOUND", "git": GIT}
    try:
        subprocess.run([GIT, "add", "-A"], cwd=WORKSPACE, check=True, capture_output=True)
        proc = subprocess.run(
            [GIT, "commit", "-m", message], cwd=WORKSPACE, capture_output=True, text=True, encoding="utf-8"
        )
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": "GIT_FAILED", "detail": str(exc)}
    return {"ok": proc.returncode == 0, "stdout": (proc.stdout or "").strip(), "stderr": (proc.stderr or "").strip()}


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="标记文章已发布并记账")
    ap.add_argument("target", help="slug 或文件路径")
    ap.add_argument("--date", help="发布日期，默认今天（东八区）")
    ap.add_argument("--ai-declared", help="发布时平台侧的 AI 声明，如 AI创作")
    ap.add_argument("--no-commit", action="store_true", help="只改文件，不提交 git")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    path = resolve(args.target)
    date = args.date or datetime.now(CST).strftime("%Y-%m-%d")
    updates = {"status": "published", "published_at": date}
    if args.ai_declared:
        updates["ai_declared"] = args.ai_declared

    title = title_of(path)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "path": path, "updates": updates}, ensure_ascii=False, indent=2))
        return 0

    update_front_matter(path, updates)
    append_changelog(date, title, path)
    commit = {"ok": False, "reason": "SKIPPED"}
    if not args.no_commit:
        commit = git_commit([path, CHANGELOG], f"发布：{title}")

    payload = {
        "ok": True,
        "path": path,
        "title": title,
        "date": date,
        "updates": updates,
        "changelog": CHANGELOG,
        "commit": commit,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
