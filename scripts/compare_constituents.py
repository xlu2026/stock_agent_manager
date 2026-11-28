"""当前指数成分 vs 快照最新时点成分（只能验证最新一天）。

AkShare 免费接口没有历史时点成分，所以这里不做“历史 PIT 复核”，
只回答“最新一天的名单是否对得上”。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _latest_members(snapshot: str) -> tuple[str, set[str]]:
    path = os.path.join(snapshot, "universe.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig"))) if os.path.exists(path) else []
    if not rows:
        return "", set()
    latest = max(r["date"] for r in rows)
    return latest, {r["asset"] for r in rows if r["date"] == latest}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="当前指数成分 vs 快照最新成分")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--index", default="000300")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    from quant.providers.akshare import fetch_current_constituents

    latest, base = _latest_members(args.snapshot)
    current = set(fetch_current_constituents(args.index))
    missing = sorted(current - base)
    extra = sorted(base - current)
    result = {
        "snapshot": os.path.abspath(args.snapshot),
        "index": args.index,
        "snapshot_latest_date": latest,
        "snapshot_members": len(base),
        "akshare_current_members": len(current),
        "overlap": len(base & current),
        "in_akshare_not_snapshot": missing[:30],
        "in_snapshot_not_akshare": extra[:30],
        "note": "AkShare 免费接口只有当前成分，无法验证历史时点名单；本报告只对最新一天",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
