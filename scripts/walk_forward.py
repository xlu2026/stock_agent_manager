"""滚动 walk-forward：训练集选参，测试集只跑一次。"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.walkforward import baseline_spec, fixed_spec, grid_specs, make_folds, test_spec  # noqa: E402


def _latest_dir() -> str:
    from quant.data_pointer import read_pointer

    return read_pointer()["dir"]


def _run(spec: dict, out_path: str, data_dir: str) -> dict | None:
    from agents.agent1 import run

    env = run(spec, out_path, data_dir=data_dir, internal_spec=True)
    if env.get("status") != "ok":
        print("  rejected:", env.get("summary"), file=sys.stderr)
        return None
    return env


def _brief(env: dict, spec: dict) -> dict:
    m = env["summary"]["metrics"]
    return {
        "id": env["id"],
        "spec": spec,
        "cagr": m.get("cagr"),
        "sharpe": m.get("sharpe"),
        "max_drawdown": m.get("max_drawdown"),
        "excess_cagr": m.get("excess_cagr"),
        "total_return": m.get("total_return"),
        "turnover": m.get("annual_turnover"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="滚动 walk-forward（走 Agent 1）")
    ap.add_argument("--data-dir")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "output", "walk_forward"))
    ap.add_argument("--train-start", default="2020-03-02")
    ap.add_argument("--first-test-year", type=int, default=2023)
    ap.add_argument("--last-test-year", type=int, default=2026)
    ap.add_argument("--weighting", default="equal", choices=("equal", "inverse_vol"))
    args = ap.parse_args(argv)
    data_dir = args.data_dir or _latest_dir()
    out_dir = os.path.join(args.out_dir, args.weighting)
    os.makedirs(out_dir, exist_ok=True)
    envelope_dir = os.path.join(out_dir, "envelopes")
    os.makedirs(envelope_dir, exist_ok=True)
    with open(os.path.join(data_dir, "calendar.csv"), encoding="utf-8-sig") as fh:
        import csv

        calendar = [r["date"] for r in csv.DictReader(fh)]
    folds = make_folds(calendar, args.train_start, args.first_test_year, args.last_test_year)
    results = []
    for fold in folds:
        print(f"fold {fold['test_year']}: train {fold['train_start']}..{fold['train_end']} "
              f"test {fold['test_start']}..{fold['test_end']}", flush=True)
        train = []
        for idx, spec in enumerate(grid_specs(fold, weighting=args.weighting)):
            env = _run(spec, os.path.join(envelope_dir, f"train_{fold['test_year']}_{idx:02d}.json"), data_dir)
            if env:
                train.append(_brief(env, spec))
        if not train:
            continue
        best = max(train, key=lambda x: x["sharpe"] if x["sharpe"] is not None else -99)
        best_params = best["spec"]["params"]["factors"]
        best_top_k = best["spec"]["top_k"]
        test_env = _run(
            test_spec(fold, best_params, best_top_k, args.weighting),
            os.path.join(envelope_dir, f"test_{fold['test_year']}_winner.json"),
            data_dir,
        )
        fixed_env = _run(
            fixed_spec(fold, args.weighting),
            os.path.join(envelope_dir, f"test_{fold['test_year']}_fixed.json"),
            data_dir,
        )
        base_env = _run(
            baseline_spec(fold),
            os.path.join(envelope_dir, f"test_{fold['test_year']}_baseline.json"),
            data_dir,
        )
        results.append(
            {
                "fold": fold,
                "train_best": best,
                "test_winner": _brief(test_env, test_spec(fold, best_params, best_top_k, args.weighting)) if test_env else None,
                "test_fixed": _brief(fixed_env, fixed_spec(fold, args.weighting)) if fixed_env else None,
                "test_baseline": _brief(base_env, baseline_spec(fold)) if base_env else None,
                "n_train_trials": len(train),
            }
        )
    output = {"data_dir": data_dir, "weighting": args.weighting, "folds": results}
    with open(os.path.join(out_dir, "walk_forward.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    lines = ["# 滚动 walk-forward", "", "| 测试年 | 训练赢家 | 训练Sharpe | 测试CAGR | 测试Sharpe | 测试超额 | 固定50/50测试CAGR | 基准测试CAGR |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        b = r["train_best"]
        tw = r["test_winner"] or {}
        fx = r["test_fixed"] or {}
        bl = r["test_baseline"] or {}
        lines.append(
            f"| {r['fold']['test_year']} | {b['spec']['params']['factors']} top{b['spec']['top_k']} | "
            f"{b['sharpe']:.3f} | {tw.get('cagr', 0):.3f} | {tw.get('sharpe', 0):.3f} | "
            f"{tw.get('excess_cagr', 0):.4f} | {fx.get('cagr', 0):.3f} | {bl.get('cagr', 0):.3f} |"
        )
    with open(os.path.join(out_dir, "walk_forward.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(json.dumps({"out_dir": args.out_dir, "folds": len(results)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
