"""把本地提案生成 SmartX 下单 CSV（只生成文件，不提交）。

    python scripts\\make_smartx_csv.py --proposal prop-xxxxxxxxxx --account 12345678
    python scripts\\make_smartx_csv.py --proposal prop-a --proposal prop-b --quotes quotes.json
    python scripts\\make_smartx_csv.py --cancel 40126371980117969 --account 12345678
    python scripts\\make_smartx_csv.py --proposal prop-x --dry-run

生成后仍需人工：
    1. 在 SmartX CLI 执行 startCSV <生成的 csv>
    2. 在确认框核对并点「下单」
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.broker.proposals import ProposalError, load as load_proposal  # noqa: E402
from quant.broker.smartx_csv import (  # noqa: E402
    DEFAULT_IN_DIR,
    SmartxCsvError,
    write_batch,
)

CONFIG_PATH = os.path.join(ROOT, "config", "smartx.json")


def _config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _setting(env_name: str, key: str, default: str = "") -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    value = str(_config().get(key) or "").strip()
    return value or default


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 SmartX 下单/撤单 CSV（不提交）")
    ap.add_argument("--proposal", action="append", default=[], help="提案 id，可重复")
    ap.add_argument("--cancel", action="append", default=[], help="要撤单的 orderXtpId，可重复")
    ap.add_argument("--account", help="资金账号；默认读 SMARTX_ACCOUNT 或 config/smartx.json")
    ap.add_argument("--out-dir", default=None, help=f"CSV 输出目录，默认 {DEFAULT_IN_DIR}")
    ap.add_argument("--quotes", help="不复权报价 JSON：{symbol: {last, limit_up, limit_down}}")
    ap.add_argument("--strict", action="store_true", help="有告警时拒绝生成")
    ap.add_argument("--allow-unchecked", action="store_true", help="没有 quotes 时仍用快照价（后复权，可能被拒单）")
    ap.add_argument("--allow-repeat", action="store_true", help="允许同一提案重复生成")
    ap.add_argument("--dry-run", action="store_true", help="只打印 CSV，不落盘")
    args = ap.parse_args(argv)

    account = str(args.account or _setting("SMARTX_ACCOUNT", "account")).strip()
    out_dir = args.out_dir or _setting("SMARTX_IN_DIR", "in_dir", DEFAULT_IN_DIR)
    if not args.proposal and not args.cancel:
        print("至少给一个 --proposal 或 --cancel", file=sys.stderr)
        return 2
    if not account:
        print("缺少资金账号：--account、SMARTX_ACCOUNT 或 config/smartx.json 的 account", file=sys.stderr)
        return 2

    quotes = None
    if args.quotes:
        try:
            with open(args.quotes, encoding="utf-8-sig") as fh:
                quotes = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"读取 quotes 失败：{exc}", file=sys.stderr)
            return 2

    proposals = []
    for pid in args.proposal:
        try:
            proposals.append(load_proposal(pid))
        except ProposalError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

    try:
        result = write_batch(
            proposals,
            account,
            out_dir=out_dir,
            cancels=args.cancel,
            quotes=quotes,
            strict=args.strict,
            allow_repeat=args.allow_repeat,
            allow_unchecked=args.allow_unchecked,
            dry_run=args.dry_run,
        )
    except SmartxCsvError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(result["csv"])
        for warning in result["warnings"]:
            print(f"WARN: {warning}", file=sys.stderr)
        return 0

    print(json.dumps({k: result[k] for k in ("batch_id", "path", "sha256", "proposal_ids", "cancels")}, ensure_ascii=False, indent=2))
    for warning in result["warnings"]:
        print(f"WARN: {warning}", file=sys.stderr)
    print("\n下一步（仍需人工）：")
    print("  1) 客户端 → 下单 → CSV → 选择上传 → 选这个文件：")
    print(f"     {result['path']}")
    print("  2) 核对代码/价格/数量/方向，点「下单」")
    print("  3) 等自动导出后跑：python scripts\\reconcile_smartx.py --archive")
    print("  （没有 GUI 时才退回 CLI：startCSV <上面的路径>）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
