"""把两份快照放在同一组参数下对照：回测指标 + 四因子 IC。

用途：真实数据快照 vs 仓库合成样本，看哪些"结论"其实是数据造成的。

    python scripts\\compare_datasets.py ^
        --a quant\\data --b C:\\...\\real40 ^
        --label-a 合成样本 --label-b 真实40 ^
        --start 2020-01-02 --end 2024-12-31 --top-k 8 --cost-bps 10 ^
        --out output\\reports\\real_vs_synthetic.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.console import force_utf8  # noqa: E402
from quant.data import DATA_DIR_ENV, load_panel  # noqa: E402
from quant.engine import run_backtest, run_factor_analysis  # noqa: E402
from quant.spec import FACTORS, parse_spec  # noqa: E402

METRIC_KEYS = ("total_return", "cagr", "sharpe", "max_drawdown", "annual_turnover", "benchmark_cagr")


def analyze(data_dir: str, args) -> dict:
    os.environ[DATA_DIR_ENV] = os.path.abspath(data_dir)
    panel = load_panel()
    out = {
        "data_dir": os.path.abspath(data_dir),
        "universe": panel.universe,
        "data_version": panel.data_version,
        "data_source": panel.source,
        "assets": len(panel.assets),
        "dates": len(panel.dates),
        "start": panel.dates[0],
        "end": panel.dates[-1],
        "filled_rows": panel.filled_rows,
        "point_in_time_universe": panel.has_point_in_time_universe(),
        "factors": {},
    }
    for factor in sorted(FACTORS):
        spec = parse_spec(
            {
                "factor": factor,
                "universe": panel.universe,
                "start": args.start,
                "end": args.end,
                "rebalance": args.rebalance,
                "top_k": args.top_k,
                "cost_bps": args.cost_bps,
            }
        )
        bt = run_backtest(spec)
        fa = run_factor_analysis(spec)
        out["factors"][factor] = {
            "metrics": {k: bt.metrics[k] for k in METRIC_KEYS},
            "experiment_id": bt.experiment_id,
            "ic_mean": fa["ic_mean"],
            "ic_ir": fa["ic_ir"],
            "top_minus_bottom": fa["top_minus_bottom"],
            "monotonic": fa["monotonic"],
        }
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python scripts/compare_datasets.py")
    p.add_argument("--a", required=True, help="第一份快照目录")
    p.add_argument("--b", required=True, help="第二份快照目录")
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.add_argument("--start", default="2020-01-02")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--rebalance", default="M")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--cost-bps", type=float, default=10.0)
    p.add_argument("--out", help="结果 JSON 路径")
    return p


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)
    result = {args.label_a: analyze(args.a, args), args.label_b: analyze(args.b, args)}
    payload = {
        "schema": "nerve.dataset_comparison/v1",
        "params": {
            "start": args.start,
            "end": args.end,
            "rebalance": args.rebalance,
            "top_k": args.top_k,
            "cost_bps": args.cost_bps,
        },
        "datasets": result,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"写出 {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
