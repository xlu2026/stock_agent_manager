"""把 QMT 导出的日线 close 导入成 v2 快照（OHLC 用 close 近似）。"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers.contract import Snapshot, write_snapshot  # noqa: E402


def _read(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build(bars_path: str, base_snapshot: str, source: str = "qmt") -> tuple[Snapshot, str]:
    with open(os.path.join(base_snapshot, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    base_assets = set(manifest.get("assets") or [])
    base_calendar = [r["date"] for r in _read(os.path.join(base_snapshot, "calendar.csv"))]
    base_universe = _read(os.path.join(base_snapshot, "universe.csv"))
    fund_path = os.path.join(base_snapshot, "fundamentals.csv")
    base_fund = _read(fund_path) if os.path.exists(fund_path) else []
    bars = _read(bars_path)
    latest: dict[tuple[str, str], float] = {}
    for row in bars:
        day = str(row.get("date") or "")[:10]
        asset = str(row.get("asset") or "").strip()
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if day and asset in base_assets and close > 0:
            latest[(day, asset)] = close
    if not latest:
        raise SystemExit("没有可用 QMT bars")
    bar_assets = {a for _, a in latest}
    base_fund = [r for r in base_fund if r.get("asset") in bar_assets]
    dates = sorted({d for d, _ in latest if d in set(base_calendar)})
    if not dates:
        raise SystemExit("QMT bars 日期与 base calendar 没有交集")
    prices = [
        {
            "date": d,
            "asset": a,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 1,
            "adj_factor": 1.0,
        }
        for (d, a), c in sorted(latest.items())
        if d in set(dates)
    ]
    universe = [
        r
        for r in base_universe
        if r.get("date") in set(dates) and r.get("asset") in {a for _, a in latest}
    ]
    snap = Snapshot(
        universe=manifest.get("universe") or "hs300_40_pit",
        source=source,
        provider="qmt",
        adjust_mode="backward",
        prices=prices,
        fundamentals=base_fund,
        universe_rows=universe,
        calendar=[{"date": d} for d in dates],
        notes={
            "provider": "qmt",
            "price_construction": "qmt_close_only",
            "base_snapshot": os.path.abspath(base_snapshot),
            "ohlc_warning": "OHLC 全部用 close 近似；只适合价格因子对齐",
        },
    )
    return snap, os.path.abspath(base_snapshot)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QMT bars -> v2 快照")
    ap.add_argument("--bars", required=True)
    ap.add_argument("--base-snapshot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="qmt")
    args = ap.parse_args(argv)
    snap, base = build(args.bars, args.base_snapshot, args.source)
    manifest = write_snapshot(args.out, snap)
    print(
        json.dumps(
            {
                "out_dir": os.path.abspath(args.out),
                "base_snapshot": base,
                "data_version": manifest["data_version"],
                "assets": len(manifest["assets"]),
                "rows": manifest["rows"],
                "start": manifest["start"],
                "end": manifest["end"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
