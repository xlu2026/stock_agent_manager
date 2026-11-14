"""读取 SmartX 自动导出的交易 CSV，和本地提案对账（只读，不下单）。

    python scripts\\reconcile_smartx.py
    python scripts\\reconcile_smartx.py --dir C:\\AI_workspace\\smartx_client\\out\\orders
    python scripts\\reconcile_smartx.py --archive
    python scripts\\reconcile_smartx.py --strict   # 有拒单/未匹配提案时退出码 2

导出文件是覆盖式全量快照；脚本按 `rowId` 把委托对回提案，不改任何状态。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker.smartx_export import (  # noqa: E402
    SmartxExportError,
    archive,
    load_export,
    load_proposals,
    reconcile,
)

DEFAULT_EXPORT_DIR = os.environ.get("SMARTX_EXPORT_DIR") or r"C:\AI_workspace\smartx_client\out\orders"
DEFAULT_PROPOSALS = os.path.join(ROOT, "output", "broker", "proposals")
DEFAULT_OUT = os.path.join(ROOT, "output", "reports", "smartx_reconcile.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SmartX 导出对账（只读）")
    ap.add_argument("--dir", default=DEFAULT_EXPORT_DIR, help="自动导出目录")
    ap.add_argument("--proposals", default=DEFAULT_PROPOSALS, help="本地提案目录")
    ap.add_argument("--out", default=DEFAULT_OUT, help="对账 JSON 输出路径")
    ap.add_argument("--archive", action="store_true", help="把当前 6 个 CSV 复制一份带时间戳的归档")
    ap.add_argument("--strict", action="store_true", help="有拒单或未匹配提案时退出码 2")
    args = ap.parse_args(argv)

    try:
        export = load_export(args.dir)
    except SmartxExportError as exc:
        print(f"读取导出失败：{exc}", file=sys.stderr)
        return 2
    proposals = load_proposals(args.proposals)
    result = reconcile(export, proposals)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    summary = result["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.archive:
        target = archive(args.dir)
        print(f"已归档：{target}")
    print(f"对账 JSON：{args.out}")

    if args.strict and (summary["rejected"] or result["unmatched_proposals"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
