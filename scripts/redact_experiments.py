"""把已有实验记录里的个股代码搬到 experiments/.private/，公开记录只留脱敏字段。

    python scripts/redact_experiments.py --dry-run
    python scripts/redact_experiments.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant import experiments as exp_store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="实验记录持仓脱敏")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(os.path.join(exp_store.exp_dir(), "exp-*.json")))
    changed = 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        holdings = record.get("holdings") or []
        has_names = any("names" in row for row in holdings)
        if not has_names:
            if not record.get("holdings_redacted"):
                record["holdings_redacted"] = True
                if not args.dry_run:
                    exp_store._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                changed += 1
            continue
        public, private = exp_store._split_holdings(holdings)
        record["holdings"] = public
        record["holdings_redacted"] = True
        if args.dry_run:
            print(f"[dry-run] {os.path.basename(path)}: {len(private)} 条持仓待搬")
            continue
        exp_store._atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        exp_store._write_private(record["experiment_id"], private, exp_store._now())
        print(f"{os.path.basename(path)}: 已脱敏 {len(private)} 条持仓")
        changed += 1
    print(f"共处理 {changed} 个实验记录（总 {len(paths)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
