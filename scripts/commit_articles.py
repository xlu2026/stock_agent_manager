r"""在写作工作区提交一次 git。

    python scripts\commit_articles.py --message "量化研究 004：补数据源一节"
    python scripts\commit_articles.py --message "推送草稿：xxx" --dry-run

写作会话没有 shell，提交这一步只能由主会话或人来做；这个脚本把命令固定下来，
省得每次回忆 MinGit 的路径和 add/commit 的顺序。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.console import force_utf8  # noqa: E402

WORKSPACE = os.environ.get("WECHAT_WORKSPACE") or r"C:\AI_workspace\wechat_writing"
GIT = os.environ.get("GIT_EXE") or r"C:\AI_workspace\_tools\MinGit\cmd\git.exe"


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="提交写作工作区的改动")
    ap.add_argument("--message", "-m", required=True, help="提交信息：哪一篇、改了什么、为什么")
    ap.add_argument("--path", action="append", help="只提交指定路径；缺省提交全部改动")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(GIT):
        print(json.dumps({"ok": False, "reason": "GIT_NOT_FOUND", "git": GIT}, ensure_ascii=False, indent=2))
        return 2
    if not os.path.isdir(os.path.join(WORKSPACE, ".git")):
        print(json.dumps({"ok": False, "reason": "NOT_A_REPO", "workspace": WORKSPACE}, ensure_ascii=False, indent=2))
        return 2

    add_cmd = [GIT, "add"] + (args.path or ["-A"])
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "workspace": WORKSPACE, "add": add_cmd, "message": args.message}, ensure_ascii=False, indent=2))
        return 0

    subprocess.run(add_cmd, cwd=WORKSPACE, check=True, capture_output=True)
    proc = subprocess.run(
        [GIT, "commit", "-m", args.message], cwd=WORKSPACE, capture_output=True, text=True, encoding="utf-8"
    )
    ok = proc.returncode == 0
    print(
        json.dumps(
            {
                "ok": ok,
                "workspace": WORKSPACE,
                "message": args.message,
                "stdout": (proc.stdout or "").strip()[-400:],
                "stderr": (proc.stderr or "").strip()[-400:],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
