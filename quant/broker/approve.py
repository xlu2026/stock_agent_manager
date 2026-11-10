"""人工批准下单提案的命令行工具。

    python -m quant.broker.approve <提案ID>

这是**唯一**能写批准记录的入口。量化 Agent 没有 shell，因此它无法自己执行这一步——
人工确认不是靠提示词约束，而是靠能力隔离。

看清楚再按 yes：批准记录绑定的是提案内容的哈希，批准后内容被改会直接失效。
"""
from __future__ import annotations

import argparse
import sys

from ..console import force_utf8
from . import proposals


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    ap = argparse.ArgumentParser(description="批准一笔下单提案（人工闸门）")
    ap.add_argument("proposal_id")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认（仅供脚本化测试，日常别用）")
    args = ap.parse_args(argv)

    try:
        payload = proposals.load(args.proposal_id)
    except proposals.ProposalError as exc:
        print(exc, file=sys.stderr)
        return 2

    print("=" * 56)
    print(f"提案        {payload['proposal_id']}")
    print(f"标的        {payload['symbol']}")
    print(f"方向/数量   {payload['side']} {payload['quantity']}")
    print(f"类型        {payload['order_type']}" + (f"（限价 {payload['limit_price']}）" if payload["limit_price"] else ""))
    print(f"参考价      {payload['price_snapshot']}")
    print(f"预估金额    {payload['est_notional']}")
    print(f"来源实验    {payload['experiment_id']}")
    print(f"备注        {payload['note']}")
    print(f"有效期至    {payload['expires_utc']}")
    print(f"内容指纹    {payload['sha256'][:16]}…")
    print("=" * 56)

    if not args.yes:
        answer = input("确认批准这笔下单？输入 yes 继续：").strip().lower()
        if answer != "yes":
            print("已取消，未写入批准记录。")
            return 1

    try:
        record = proposals.approve(args.proposal_id, approved_by="human:cli")
    except proposals.ProposalError as exc:
        print(exc, file=sys.stderr)
        return 2

    print(f"已批准：{record['proposal_id']} @ {record['approved_utc']}")
    print("下一步（由 Agent 执行）： broker_submit_order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
