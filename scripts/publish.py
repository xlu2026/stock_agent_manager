"""发布台 CLI：status / prepare / done。

    python scripts\\publish.py status
    python scripts\\publish.py prepare agent-approval-002
    python scripts\\publish.py done --platform zhihu agent-approval-002 --url https://zhuanlan.zhihu.com/p/...

只读写本地文件；不发布、不碰浏览器、不读平台凭据。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.console import force_utf8  # noqa: E402
from writing import publishing  # noqa: E402


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def _pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - _width(text))


def _table(data: dict) -> str:
    rows = data["articles"]
    if not rows:
        return "没有找到可发布的文章。"
    headers = ("slug", "栏目", "微信", "知乎", "下一步")
    w0 = max([_width(headers[0])] + [_width(r["slug"]) for r in rows])
    w1 = max([_width(headers[1])] + [_width(r["category"]) for r in rows])
    w2 = max([_width(headers[2])] + [_width(r["wechat"]["label"]) for r in rows])
    w3 = max([_width(headers[3])] + [_width(r["zhihu"]["state"]) for r in rows])

    def line(values: tuple[str, ...]) -> str:
        out = "  ".join(_pad(values[i], w) for i, w in enumerate((w0, w1, w2, w3)))
        return out + (f"  {values[4]}" if len(values) > 4 else "")

    out = [line(headers), line(tuple("-" * w for w in (w0, w1, w2, w3)))]
    for row in rows:
        actions = "；".join(row["actions"]) or "-"
        out.append(
            line(
                (
                    row["slug"],
                    row["category"],
                    row["wechat"]["label"],
                    row["zhihu"]["state"],
                    actions,
                )
            )
        )
    summary = data["summary"]
    out.append("")
    tail = (
        f"共 {summary['total']} 篇：微信已发 {summary['wechat_published']}，"
        f"知乎已发 {summary['zhihu_published']}，有待办 {summary['with_actions']}"
    )
    if summary.get("skipped"):
        tail += f"；跳过存档 {summary['skipped']}"
    out.append(tail)
    return "\n".join(out)


def _markdown(data: dict) -> str:
    lines = ["| slug | 栏目 | 微信 | 知乎 | 下一步 |", "|---|---|---|---|---|"]
    for row in data["articles"]:
        actions = "；".join(row["actions"]) or "-"
        lines.append(f"| {row['slug']} | {row['category']} | {row['wechat']['label']} | {row['zhihu']['state']} | {actions} |")
    return "\n".join(lines)


def _cmd_status(args) -> int:
    data = publishing.scan()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(_markdown(data))
    else:
        print(_table(data))
    return 0


def _push_wechat(path: Path, category: str) -> int:
    script = os.path.join(ROOT, "scripts", "push_draft.py")
    print(f"\n推微信草稿：{path}")
    proc = subprocess.run(
        [sys.executable, script, "--file", str(path), "--category", category],
        cwd=ROOT,
    )
    if proc.returncode != 0:
        print("草稿推送失败；卡片仍可用，修好后重跑 push_draft.py。")
    return proc.returncode


def _cmd_prepare(args) -> int:
    result = publishing.prepare(
        args.target,
        platform=args.platform,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"卡片：{result['card']}")
        export = result.get("export")
        if export:
            print(f"知乎正文：{export['html_path']}")
            print(f"知乎元数据：{export['meta_path']}")
        print()
        print(Path(result["card"]).read_text(encoding="utf-8"))
    if args.push_wechat and args.platform in ("all", "wechat"):
        if result.get("wechat_status") == "published":
            print("\n微信已是发布状态，跳过推草稿。")
            return 0
        return _push_wechat(Path(result["path"]), str(result.get("category") or ""))
    return 0


def _cmd_done(args) -> int:
    if args.platform == "zhihu":
        if not args.url:
            raise publishing.PublishError("--platform zhihu 需要 --url")
        result = publishing.done_zhihu(args.target, args.url, date=args.date, force=args.force)
        print(f"已回填知乎：{result['canonical']}（{result['published_at']}）")
        print(f"sidecar：{result['sidecar']}")
    else:
        result = publishing.done_wechat(args.target, date=args.date)
        if result.get("already"):
            print(f"已经是发布状态：{result['slug']}（{result['published_at']}）")
        else:
            print(f"已回填微信：{result['title']}（{result['published_at']}）")
            print(f'提交工作区：python scripts\\commit_articles.py -m "发布：{result["title"]}"')
    return 0


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    parser = argparse.ArgumentParser(prog="publish", description="发布台：状态、发布卡片、回填（不发布）")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="汇总微信/知乎发布状态")
    status.add_argument("--json", action="store_true")
    status.add_argument("--markdown", action="store_true")
    status.set_defaults(func=_cmd_status)

    prepare = sub.add_parser("prepare", help="生成知乎导出与发布卡片")
    prepare.add_argument("target", help="slug 或文章路径")
    prepare.add_argument("--platform", choices=["all", "wechat", "zhihu"], default="all")
    prepare.add_argument("--push-wechat", action="store_true", help="顺便把草稿推到公众号草稿箱")
    prepare.add_argument("--json", action="store_true")
    prepare.set_defaults(func=_cmd_prepare)

    done = sub.add_parser("done", help="人工发布后回填状态")
    done.add_argument("target", help="slug 或文章路径")
    done.add_argument("--platform", choices=["wechat", "zhihu"], required=True)
    done.add_argument("--url", help="知乎文章 URL（仅 zhihu）")
    done.add_argument("--date", help="发布日期，默认今天（东八区）")
    done.add_argument("--force", action="store_true", help="覆盖已登记的不同知乎 URL")
    done.set_defaults(func=_cmd_done)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except publishing.PublishError as exc:
        print(f"发布台：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
