"""比较两份 v2 快照：价格/收益差异、缺失行、时点成分差异。

用途：第二数据源（AkShare）与主源（baostock）做交叉验证。
复权基准可能不同，所以同时看“价格比”和“日收益差”：
收益差小、价格比恒定，说明只是复权基准不同，不是数据错误。

    python scripts\\compare_snapshots.py --a snapshots\\real40_pit --b snapshots\\real40_pit_akshare
"""
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


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.DictReader(fh)]


def _manifest(directory: str) -> dict:
    path = os.path.join(directory, "manifest.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"没有 manifest.json：{directory}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _prices(directory: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for row in _read_csv(os.path.join(directory, "prices.csv")):
        try:
            out[row["asset"]][row["date"]] = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _universe(directory: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for row in _read_csv(os.path.join(directory, "universe.csv")):
        if row.get("date") and row.get("asset"):
            out[row["date"]].add(row["asset"])
    return out


def _fundamentals(directory: str) -> dict[tuple[str, str], dict[str, float]]:
    out = {}
    for row in _read_csv(os.path.join(directory, "fundamentals.csv")):
        try:
            out[(row["asset"], row["report_date"])] = {
                "book": float(row["book"]),
                "earnings": float(row["earnings"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    ordered = sorted(xs)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    ordered = sorted(xs)
    idx = min(len(ordered) - 1, int(len(ordered) * q))
    return ordered[idx]


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _returns(prices: dict[str, float], dates: list[str]) -> dict[str, float]:
    out = {}
    ordered = [d for d in dates if d in prices]
    for prev, cur in zip(ordered, ordered[1:]):
        if prices[prev] > 0:
            out[cur] = prices[cur] / prices[prev] - 1.0
    return out


def compare(a: str, b: str, max_return_diff: float = 0.002) -> dict:
    ma, mb = _manifest(a), _manifest(b)
    pa, pb = _prices(a), _prices(b)
    common_assets = sorted(set(pa) & set(pb))
    common_dates = sorted(set().union(*[set(v) for v in pa.values()]) & set().union(*[set(v) for v in pb.values()])) if pa and pb else []
    rows_a = sum(len(v) for v in pa.values())
    rows_b = sum(len(v) for v in pb.values())

    price_stats = []
    return_diffs = []
    gaps = []
    for asset in common_assets:
        dates = sorted(set(pa[asset]) & set(pb[asset]))
        if not dates:
            continue
        ratios = [pa[asset][d] / pb[asset][d] for d in dates if pb[asset][d] > 0]
        ra = _returns(pa[asset], dates)
        rb = _returns(pb[asset], dates)
        for d in sorted(set(ra) & set(rb)):
            diff = abs(ra[d] - rb[d])
            return_diffs.append(diff)
            gaps.append((round(diff, 8), asset, d, round(ra[d], 6), round(rb[d], 6)))
        price_stats.append(
            {
                "asset": asset,
                "days": len(dates),
                "ratio_median": round(_mean(ratios), 6),
                "ratio_cv": round(_stdev(ratios) / _mean(ratios), 8) if _mean(ratios) else None,
            }
        )

    all_ratios = [s["ratio_median"] for s in price_stats if s["ratio_median"]]
    ratio_cv = (
        round(_stdev(all_ratios) / _mean(all_ratios), 8) if all_ratios and _mean(all_ratios) else None
    )
    common_date_set = set(common_dates)
    common_rows_a = sum(len(set(pa[x]) & common_date_set) for x in common_assets)
    common_rows_b = sum(len(set(pb[x]) & common_date_set) for x in common_assets)
    overlap = sum(
        len((set(pa[x]) & set(pb[x])) & common_date_set) for x in common_assets
    )
    missing_a = common_rows_a - overlap
    missing_b = common_rows_b - overlap

    uni_a, uni_b = _universe(a), _universe(b)
    universe_diff_dates = []
    if uni_a and uni_b:
        for d in sorted(set(uni_a) & set(uni_b)):
            if uni_a[d] != uni_b[d]:
                universe_diff_dates.append(d)

    fund_a, fund_b = _fundamentals(a), _fundamentals(b)
    fund_common = sorted(set(fund_a) & set(fund_b))
    book_diffs = []
    earnings_diffs = []
    for key in fund_common:
        ba, bb = fund_a[key]["book"], fund_b[key]["book"]
        if bb:
            book_diffs.append(abs(ba - bb) / abs(bb))
        earnings_diffs.append(abs(fund_a[key]["earnings"] - fund_b[key]["earnings"]))
    fundamentals = {
        "rows_a": len(fund_a),
        "rows_b": len(fund_b),
        "common": len(fund_common),
        "book_diff_median": round(_median(book_diffs), 6) if book_diffs else None,
        "book_diff_p95": round(_percentile(book_diffs, 0.95), 6) if book_diffs else None,
        "book_diff_max": round(max(book_diffs), 6) if book_diffs else None,
        "earnings_diff_median": round(_median(earnings_diffs), 6) if earnings_diffs else None,
        "earnings_diff_p95": round(_percentile(earnings_diffs, 0.95), 6) if earnings_diffs else None,
        "earnings_diff_max": round(max(earnings_diffs), 6) if earnings_diffs else None,
    }

    max_diff = max(return_diffs) if return_diffs else None
    p95 = sorted(return_diffs)[int(len(return_diffs) * 0.95)] if return_diffs else None
    if max_diff is None:
        verdict = "fail"
    elif max_diff <= max_return_diff:
        verdict = "ok"
    elif p95 is not None and p95 <= max_return_diff:
        verdict = "warn_outliers"
    else:
        verdict = "warn"
    return {
        "a": {"dir": os.path.abspath(a), "source": ma.get("source"), "data_version": "dv-" + str(ma.get("sha256", ""))[:12], "rows": rows_a},
        "b": {"dir": os.path.abspath(b), "source": mb.get("source"), "data_version": "dv-" + str(mb.get("sha256", ""))[:12], "rows": rows_b},
        "common_assets": len(common_assets),
        "common_dates": len(common_dates),
        "common_rows_a": common_rows_a,
        "common_rows_b": common_rows_b,
        "price_ratio_median": round(_mean(all_ratios), 6) if all_ratios else None,
        "price_ratio_cv": ratio_cv,
        "return_diff_max": round(max_diff, 8) if max_diff is not None else None,
        "return_diff_p95": round(p95, 8) if p95 is not None else None,
        "missing_rows_a": missing_a,
        "missing_rows_b": missing_b,
        "universe_diff_dates": len(universe_diff_dates),
        "fundamentals": fundamentals,
        "verdict": verdict,
        "outliers": [
            {"diff": diff, "asset": asset, "date": day, "a_return": ra, "b_return": rb}
            for diff, asset, day, ra, rb in sorted(gaps, reverse=True)[:10]
        ],
        "assets": price_stats,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="两份 v2 快照的交叉验证")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--max-return-diff", type=float, default=0.002)
    ap.add_argument("--out")
    ap.add_argument("--update-manifest", help="把 crosscheck 写进该快照的 manifest.json")
    args = ap.parse_args(argv)
    try:
        result = compare(args.a, args.b, args.max_return_diff)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "assets"},
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    if args.update_manifest:
        target = args.update_manifest
        if os.path.isdir(target):
            target = os.path.join(target, "manifest.json")
        with open(target, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["crosscheck"] = {
            "a": result["a"],
            "b": result["b"],
            "verdict": result["verdict"],
            "common_assets": result["common_assets"],
            "common_dates": result["common_dates"],
            "return_diff_p95": result["return_diff_p95"],
            "return_diff_max": result["return_diff_max"],
            "fundamentals": result["fundamentals"],
            "generated": "compare_snapshots.py",
        }
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
    return 0 if result["verdict"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
