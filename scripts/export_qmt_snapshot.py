"""在装了 QMT 的机器上，把终端里**已下载**的日线导出成 schema v2 快照。

2026-10 起 QMT 客户端限制联网与本地文件读写，但终端里已有的历史数据仍可读取
（用户已向券商确认）。所以这个脚本只调用**读**接口：

- 从不调用 `xtdata.download_history_data`——没有的数据就是没有，脚本不会去补；
- 只把读到的行情翻译成 v2 快照，落盘后立刻跑 `snapshot_check`。

它要跑在**能 import `xtquant` 的那个 Python** 里（通常是 QMT 安装目录的
`bin.x64` / `Lib\\site-packages`，或用 pip 装的 `xtquant`），不是在本仓库的默认
解释器里。若券商只允许在客户端进程内运行，就退回"终端内手工导出 CSV →
`python -m quant.providers.csv_import`"。

    # 先探一探本地到底有什么（不写任何文件）
    python scripts/export_qmt_snapshot.py --probe ^
        --stocks 600000.SH,000001.SZ --start 20190101 --end 20241231

    # 正式导出（可选：时点成分、财报，格式同 schema v2）
    python scripts/export_qmt_snapshot.py ^
        --stocks 600000.SH,000001.SZ --start 20190101 --end 20241231 ^
        --out snapshots\\qmt --universe csi300 ^
        --universe-file raw\\universe.csv --fundamentals raw\\fundamentals.csv

退出码：0 = 导出且体检通过；1 = 体检有 fail；2 = 环境或参数问题。
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
from quant.providers.contract import ContractError, write_snapshot  # noqa: E402
from quant.providers.csv_import import read_fundamentals, read_universe  # noqa: E402
from quant.providers.qmt import QmtProvider  # noqa: E402
from quant.providers.snapshot_check import check_snapshot  # noqa: E402


def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _universe_map(path: str | None) -> dict[str, list[str]] | None:
    if not path:
        return None
    per_date: dict[str, list[str]] = {}
    for row in read_universe(path):
        per_date.setdefault(row["date"], []).append(row["asset"])
    return {d: sorted(set(a)) for d, a in per_date.items()}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python scripts/export_qmt_snapshot.py",
        description="把 QMT 终端本地已下载的日线导出成 schema v2 快照（只读，不下载）",
    )
    p.add_argument("--start", required=True, help="起始日，YYYYMMDD 或 YYYY-MM-DD")
    p.add_argument("--end", required=True, help="结束日")
    p.add_argument("--stocks", help="逗号分隔的代码列表")
    p.add_argument("--sector", help="板块名（用 xtdata.get_stock_list_in_sector 取成分）")
    p.add_argument("--out", help="快照输出目录（--probe 时可省略）")
    p.add_argument("--universe", help="标的池名称，写进 manifest（--probe 时用 probe）")
    p.add_argument("--universe-file", help="时点成分 CSV（date, asset）")
    p.add_argument("--fundamentals", help="财报 CSV（asset, report_date, available_date, book, earnings）")
    p.add_argument("--dividend-type", default="back", choices=["none", "front", "back"])
    p.add_argument("--source", default="qmt / xtquant（终端本地缓存，只读）")
    p.add_argument("--probe", action="store_true", help="只报告本地能读到什么，不写文件")
    return p


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)

    if not args.probe and not (args.out and args.universe):
        print("导出模式需要 --out 和 --universe；只想看本地有什么请加 --probe", file=sys.stderr)
        return 2
    if not args.stocks and not args.sector:
        print("必须给 --stocks 或 --sector，否则不知道该取哪些标的", file=sys.stderr)
        return 2

    provider = QmtProvider(dividend_type=args.dividend_type)
    try:
        provider._xtdata()  # 先探依赖：xtquant 不在时报清楚，而不是在半个快照之后
    except RuntimeError as exc:
        print(f"无法使用 xtquant：{exc}", file=sys.stderr)
        return 2

    try:
        snapshot = provider.fetch(
            args.start,
            args.end,
            args.universe or "probe",
            stocks=_split(args.stocks) or None,
            sector=args.sector,
            universe_map=_universe_map(args.universe_file),
            fundamentals=read_fundamentals(args.fundamentals) if args.fundamentals else None,
        )
    except ContractError as exc:
        print(f"输入文件有问题：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"取数失败：{exc}", file=sys.stderr)
        return 2

    notes = snapshot.notes
    summary = {
        "mode": "probe" if args.probe else "export",
        "assets": len(snapshot.assets()),
        "rows": len(snapshot.prices),
        "dates": len(snapshot.dates()),
        "start": snapshot.dates()[0] if snapshot.dates() else None,
        "end": snapshot.dates()[-1] if snapshot.dates() else None,
        "suspended_filled": notes.get("suspended_filled", 0),
        "empty_symbols": notes.get("empty_symbols", []),
        "universe_point_in_time": notes.get("universe_point_in_time", False),
        "notes": notes,
    }

    if args.probe:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if notes.get("empty_symbols"):
            print(
                f"\n有 {len(notes['empty_symbols'])} 个标的本地没有数据：这些代码要在终端里补下载，"
                "或者从标的池里去掉。脚本不会替你下载。",
                file=sys.stderr,
            )
        return 0

    assert args.out and args.universe
    # fetch() 已经把 universe 写进 Snapshot；这里只覆盖来源描述，便于区分
    # "只读导出"和别的方式产出的快照。
    snapshot.source = args.source
    manifest = write_snapshot(args.out, snapshot)
    result = check_snapshot(args.out)
    summary["out_dir"] = os.path.abspath(args.out)
    summary["data_version"] = "dv-" + manifest["sha256"][:12]
    summary["check_ok"] = result["ok"]
    summary["fails"] = [c for c in result["checks"] if c["status"] == "fail"]
    summary["stats"] = result.get("stats", {})
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not result["ok"]:
        print("\n体检未通过：这份快照不要拿去回测。", file=sys.stderr)
        return 1
    print(f"\n写入 {summary['out_dir']}（{summary['data_version']}），体检通过。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
