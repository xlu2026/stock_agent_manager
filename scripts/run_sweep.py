"""跑参数网格：每个 spec 都走 Agent 1 登记实验，再做多重检验汇总。

配置示例：
{
  "name": "momentum_param",
  "base": {"strategy":"momentum_param","universe":"hs300_40_pit",
           "start":"2021-01-04","end":"2026-11-11","top_k":8,"cost_bps":10},
  "axes": {"params.lookback":[60,120,252], "params.skip":[5,10,21]}
}
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.sweeps import expand_grid, summarize  # noqa: E402


def _latest_dir() -> str | None:
    from quant.data_pointer import read_pointer

    try:
        return read_pointer()["dir"]
    except Exception:  # noqa: BLE001
        return None


def _write_md(path: str, name: str, summary: dict) -> None:
    lines = [f"# sweep: {name}", "", f"- trials: {summary['n_trials']}", ""]
    lines += ["| variant | CAGR | Sharpe | MDD | excess | p | BH q |", "|---|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        lines.append(
            f"| {r['name']} | {r['cagr']} | {r['sharpe']} | {r['max_drawdown']} | "
            f"{r['excess_cagr']} | {r['p_value']} | {r['bh_q']} |"
        )
    lines += ["", summary["warning"]]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="参数网格（走 Agent 1）")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "output", "reports", "sweeps"))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8-sig") as fh:
        config = json.load(fh)
    name = config.get("name") or "sweep"
    specs = expand_grid(config["base"], config.get("axes", {}))
    out_dir = os.path.join(args.out_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"{name}: {len(specs)} 个 spec", flush=True)
    if args.dry_run:
        print(json.dumps(specs, ensure_ascii=False, indent=2))
        return 0

    data_dir = args.data_dir or _latest_dir()
    if not data_dir:
        print("没有最新快照指针，请给 --data-dir", file=sys.stderr)
        return 2
    from agents.agent1 import run

    results = []
    for idx, spec in enumerate(specs):
        out_path = os.path.join(out_dir, f"spec_{idx:03d}.json")
        env = run(spec, out_path, data_dir=data_dir, internal_spec=True)
        if env.get("status") != "ok":
            print(f"  [{idx}] rejected: {env.get('summary')}", file=sys.stderr)
            continue
        summary = env["summary"]
        results.append(
            {
                "name": f"spec_{idx:03d}",
                "spec": spec,
                "experiment_id": env["id"],
                "metrics": summary["metrics"],
            }
        )
        print(f"  [{idx}] {env['id']} cagr={summary['metrics'].get('cagr')}", flush=True)
    summary = summarize(results)
    payload = {"name": name, "data_dir": data_dir, "specs": specs, "summary": summary, "results": results}
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    _write_md(os.path.join(out_dir, "results.md"), name, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
