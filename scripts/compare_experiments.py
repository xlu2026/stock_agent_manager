"""把多份实验信封/记录汇总成一张对照表（不重算指标）。"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if "summary" in payload:
        s = payload["summary"]
        return {
            "id": payload.get("id"),
            "spec": s.get("spec") or s.get("contract", {}).get("resolved"),
            "strategy": s.get("strategy"),
            "params": s.get("params"),
            "metrics": s.get("metrics") or {},
        }
    return {
        "id": payload.get("experiment_id"),
        "spec": payload.get("spec"),
        "strategy": (payload.get("spec") or {}).get("strategy"),
        "params": (payload.get("spec") or {}).get("params"),
        "metrics": payload.get("metrics") or {},
    }


def build(paths: list[str]) -> dict:
    rows = []
    for path in paths:
        try:
            item = load(path)
        except (OSError, ValueError):
            continue
        m = item["metrics"]
        spec = item.get("spec") or {}
        rows.append(
            {
                "file": os.path.basename(path),
                "id": item["id"],
                "strategy": item.get("strategy") or spec.get("strategy"),
                "params": item.get("params") or spec.get("params"),
                "window": f"{spec.get('start')}..{spec.get('end')}",
                "cagr": m.get("cagr"),
                "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "excess_cagr": m.get("excess_cagr"),
                "turnover": m.get("annual_turnover"),
            }
        )
    rows.sort(key=lambda r: (r["cagr"] is None, -(r["cagr"] or 0)))
    return {"count": len(rows), "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="实验对照表")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    paths = []
    for p in args.paths:
        paths.extend(glob.glob(p) if any(ch in p for ch in "*?[") else [p])
    result = build(paths)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
