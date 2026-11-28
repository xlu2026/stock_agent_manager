"""QMT 日频净值 vs 引擎 NAV 的逐日对账。"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_csv(path: str) -> dict[str, float]:
    out: dict[str, float] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return out
        date_col = next((c for c in reader.fieldnames if c.lower() in ("date", "日期")), None)
        value_col = next(
            (c for c in reader.fieldnames if c.lower() in ("net_value", "nav", "value", "净值", "单位净值")),
            None,
        )
        if not date_col or not value_col:
            raise ValueError(f"{path} 缺少 date/net_value 列，实际：{reader.fieldnames}")
        for row in reader:
            day = str(row.get(date_col) or "").strip()[:10]
            raw = row.get(value_col)
            if not day or raw in (None, ""):
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            if value > 0:
                out[day] = value
    return out


def load_experiment(experiment_id: str) -> dict[str, float]:
    path = os.path.join(ROOT, "experiments", experiment_id + ".json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    series = payload.get("nav_series") or {}
    return {str(d): float(v) for d, v in zip(series.get("dates", []), series.get("nav", []))}


def _returns(values: dict[str, float], days: list[str]) -> dict[str, float]:
    return {days[i]: values[days[i]] / values[days[i - 1]] - 1.0 for i in range(1, len(days))}


def _norm(values: dict[str, float], days: list[str]) -> dict[str, float]:
    base = values[days[0]]
    return {d: values[d] / base for d in days}


def compare(qmt: dict[str, float], engine: dict[str, float]) -> dict:
    common = sorted(set(qmt) & set(engine))
    if len(common) < 3:
        raise ValueError(f"共同净值日不足：{len(common)}")
    q = _norm(qmt, common)
    e = _norm(engine, common)
    qr = _returns(q, common)
    er = _returns(e, common)
    diffs = [qr[d] - er[d] for d in sorted(qr)]
    mean_diff = sum(diffs) / len(diffs)
    var = sum((x - mean_diff) ** 2 for x in diffs) / max(len(diffs) - 1, 1)
    te = math.sqrt(var) * math.sqrt(252)
    cov = sum((qr[d] - sum(qr.values()) / len(qr)) * (er[d] - sum(er.values()) / len(er)) for d in qr)
    vq = sum((qr[d] - sum(qr.values()) / len(qr)) ** 2 for d in qr)
    ve = sum((er[d] - sum(er.values()) / len(er)) ** 2 for d in er)
    corr = cov / math.sqrt(vq * ve) if vq > 0 and ve > 0 else 0.0
    total_diff = q[common[-1]] / e[common[-1]] - 1.0
    yearly = {}
    for year in sorted({d[:4] for d in common}):
        days = [d for d in common if d[:4] == year]
        if len(days) < 2:
            continue
        yearly[year] = {
            "qmt": round(q[days[-1]] / q[days[0]] - 1.0, 6),
            "engine": round(e[days[-1]] / e[days[0]] - 1.0, 6),
            "diff": round((q[days[-1]] / q[days[0]]) / (e[days[-1]] / e[days[0]]) - 1.0, 6),
        }
    top_days = sorted(
        ({"date": d, "diff": round(qr[d] - er[d], 6), "qmt_ret": round(qr[d], 6), "engine_ret": round(er[d], 6)} for d in qr),
        key=lambda x: abs(x["diff"]),
        reverse=True,
    )[:8]
    return {
        "common_days": len(common),
        "start": common[0],
        "end": common[-1],
        "qmt_total": round(q[common[-1]] - 1.0, 6),
        "engine_total": round(e[common[-1]] - 1.0, 6),
        "total_diff": round(total_diff, 6),
        "daily_corr": round(corr, 4),
        "tracking_error": round(te, 6),
        "mean_daily_diff": round(mean_diff, 8),
        "max_daily_diff": round(max(abs(x) for x in diffs), 6),
        "final_nav_gap": round(q[common[-1]] - e[common[-1]], 6),
        "yearly": yearly,
        "top_diff_days": top_days,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="QMT NAV vs 引擎 NAV")
    ap.add_argument("--qmt", required=True, help="QMT 导出的 date,net_value CSV")
    ap.add_argument("--experiment", help="实验 ID，使用 experiments/<id>.json 的 nav_series")
    ap.add_argument("--engine-nav", help="引擎 date,net_value CSV（与 --experiment 二选一）")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    qmt = load_csv(args.qmt)
    if not qmt:
        print(f"QMT 净值为空：{args.qmt}", file=sys.stderr)
        return 2
    if args.experiment:
        engine = load_experiment(args.experiment)
    elif args.engine_nav:
        engine = load_csv(args.engine_nav)
    else:
        print("给 --experiment 或 --engine-nav", file=sys.stderr)
        return 2
    try:
        result = compare(qmt, engine)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
