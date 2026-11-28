"""把一份已有 v2 快照的价格重建为“连续总收益价”，其余表原样保留。

用途：修复 baostock hfq 在除权日的假跳空，同时不改变标的池/时点成分/财报，
避免重新取样导致历史实验不可比。

    C:\\...\\python.exe scripts\\rebuild_continuous_snapshot.py ^
      --base-snapshot C:\\AI_workspace\\smartx_client\\out\\real40_pit_20261112_v2 ^
      --out C:\\AI_workspace\\smartx_client\\out\\real40_pit_cont_pit_20261125
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.export_baostock_snapshot import (  # noqa: E402
    _asset_to_code,
    _continuous_rows,
    _fetch_raw_prices,
    _read_rows,
    _write_csv,
)
from quant.providers.csv_import import import_snapshot  # noqa: E402


def _login():
    try:
        import baostock as bs  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("找不到 baostock，请用 SmartX 自带的 Python") from exc
    result = bs.login()
    if result.error_code != "0":
        raise SystemExit(f"baostock 登录失败：{result.error_code} {result.error_msg}")
    return bs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="保留快照结构，只重建连续价")
    ap.add_argument("--base-snapshot", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", default="baostock continuous")
    args = ap.parse_args(argv)
    base = os.path.abspath(args.base_snapshot)
    out = os.path.abspath(args.out)
    if base == out:
        print("out 不能等于 base", file=sys.stderr)
        return 2

    with open(os.path.join(base, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    start, end = manifest["start"], manifest["end"]
    assets = list(manifest["assets"])
    _, calendar = _read_rows(os.path.join(base, "calendar.csv"))
    _, universe = _read_rows(os.path.join(base, "universe.csv"))
    _, fundamentals = _read_rows(os.path.join(base, "fundamentals.csv"))
    if not calendar:
        calendar = [[d] for d in sorted({r[0] for r in _read_rows(os.path.join(base, "prices.csv"))[1]})]

    bs = _login()
    try:
        raw = _fetch_raw_prices(bs, [_asset_to_code(a) for a in assets], start, end)
    finally:
        bs.logout()

    prices: list[list] = []
    for asset in assets:
        prices.extend(_continuous_rows(asset, raw.get(asset, [])))
    if not prices:
        print("没有重建出任何价格", file=sys.stderr)
        return 2

    raw_dir = os.path.join(out, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    _write_csv(
        os.path.join(raw_dir, "prices.csv"),
        ["date", "asset", "open", "high", "low", "close", "volume", "adj_factor"],
        prices,
    )
    _write_csv(os.path.join(raw_dir, "calendar.csv"), ["date"], calendar)
    if universe:
        _write_csv(os.path.join(raw_dir, "universe.csv"), ["date", "asset"], universe)
    if fundamentals:
        _write_csv(
            os.path.join(raw_dir, "fundamentals.csv"),
            ["asset", "report_date", "available_date", "book", "earnings"],
            fundamentals,
        )

    notes = {
        "provider": "baostock",
        "adjustflag": "3+preclose(continuous)",
        "price_construction": "total_return_chain_preclose",
        "rebuilt_from": base,
        "universe_point_in_time": bool(universe),
        "membership_grid": (manifest.get("notes") or {}).get("membership_grid"),
        "membership_versions": (manifest.get("notes") or {}).get("membership_versions"),
        "survivorship": (manifest.get("notes") or {}).get("survivorship"),
        "warning": "价格是连续总收益序列，不是可直接下单的名义价",
    }
    result = import_snapshot(
        out,
        prices_path=os.path.join(raw_dir, "prices.csv"),
        universe=manifest.get("universe") or "hs300_40_pit",
        source=args.source,
        adjust_mode="backward",
        fundamentals_path=os.path.join(raw_dir, "fundamentals.csv") if fundamentals else None,
        universe_path=os.path.join(raw_dir, "universe.csv") if universe else None,
        calendar_path=os.path.join(raw_dir, "calendar.csv"),
        extra_notes=notes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
