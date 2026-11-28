"""用 AkShare 导出 v2 快照（第二位数据源，用于交叉验证）。

必须在装了 akshare 的 Python 里运行，例如 SmartX 自带：
    C:\\Users\\<you>\\AppData\\Local\\Programs\\xtp_rich_client\\bin\\cpython\\python.exe

推荐用法：复用已有快照的标的/日历/时点成分，只换价格来源：
    python scripts\\export_akshare_snapshot.py ^
        --base-snapshot C:\\AI_workspace\\smartx_client\\out\\real40_pit ^
        --out C:\\AI_workspace\\smartx_client\\out\\real40_pit_akshare
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

from quant.console import force_utf8  # noqa: E402
from quant.providers.akshare import AkshareError, build_snapshot, fetch_fundamentals  # noqa: E402
from quant.providers.contract import ContractError, write_snapshot  # noqa: E402
from quant.providers.snapshot_check import check_snapshot  # noqa: E402


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh)]


def _base_inputs(path: str, start: str | None, end: str | None):
    with open(os.path.join(path, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assets = list(manifest.get("assets") or [])
    calendar = [r["date"] for r in _read_csv(os.path.join(path, "calendar.csv"))]
    universe = _read_csv(os.path.join(path, "universe.csv"))
    lo = start or manifest.get("start")
    hi = end or manifest.get("end")
    if not lo or not hi:
        raise SystemExit("base 快照缺少 start/end，请显式给 --start/--end")
    calendar = [d for d in calendar if lo <= d <= hi]
    universe = [r for r in universe if lo <= r["date"] <= hi and r["asset"] in assets]
    return assets, calendar, universe, lo, hi


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="AkShare -> v2 快照")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-snapshot", help="复用该快照的 assets/calendar/universe")
    ap.add_argument("--symbols", help="逗号分隔，如 600000.SH,000001.SZ（无 base 时必填）")
    ap.add_argument("--universe", default="akshare_pool")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--min-coverage", type=float, default=0.9)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--fundamentals", action="store_true", help="同时导出每股净资产/TTM EPS")
    ap.add_argument("--source", default="akshare")
    args = ap.parse_args(argv)

    if args.base_snapshot:
        assets, calendar, universe, start, end = _base_inputs(args.base_snapshot, args.start, args.end)
    else:
        if not args.symbols:
            ap.error("没有 --base-snapshot 时必须给 --symbols")
        assets = [s.strip() for s in args.symbols.split(",") if s.strip()]
        calendar = None
        universe = None
        start, end = args.start, args.end
        if not start or not end:
            ap.error("没有 --base-snapshot 时必须给 --start/--end")

    print(f"AkShare: {len(assets)} 个标的，{start}..{end}", flush=True)
    fundamentals = None
    if args.fundamentals:
        print("AkShare: 拉取财报（法定截止日作为可用日）", flush=True)
        fundamentals, fwarnings = fetch_fundamentals(assets, start, end)
        for warning in fwarnings:
            print(f"WARN: {warning}", file=sys.stderr)
    try:
        snap, warnings = build_snapshot(
            assets=assets,
            start=start,
            end=end,
            universe_name=args.universe,
            source=args.source,
            calendar=calendar,
            universe_rows=universe,
            fundamentals=fundamentals,
            min_coverage=args.min_coverage,
            retries=args.retries,
            delay=args.delay,
        )
        manifest = write_snapshot(args.out, snap)
    except (AkshareError, ContractError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    check = check_snapshot(args.out)
    print(
        json.dumps(
            {
                "ok": check["ok"],
                "out_dir": os.path.abspath(args.out),
                "data_version": "dv-" + manifest["sha256"][:12],
                "assets": len(manifest["assets"]),
                "rows": manifest["rows"],
                "start": manifest["start"],
                "end": manifest["end"],
                "fails": [c for c in check["checks"] if c["status"] == "fail"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if check["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
