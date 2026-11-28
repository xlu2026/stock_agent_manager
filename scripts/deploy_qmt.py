"""从 Spec 生成 QMT 内置策略文件：只投递，不启动、不下单。

示例：
    python scripts\\deploy_qmt.py --spec output\\qmt\\spec.json ^
      --snapshot C:\\AI_workspace\\smartx_client\\out\\real40_pit_cont_pit_20261125 ^
      --account <你的资金账号> --name nfr_mom_lowvol ^
      --qmt-dir "C:\\AI_workspace\\_tools\\中泰qmt信创模拟交易端\\python"

生成后仍需在 QMT 客户端里手工导入/启动；脚本不会调用任何交易接口。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.deploy.qmt import (  # noqa: E402
    DEFAULT_CONFIG,
    QmtDeployError,
    load_account_config,
    rebalance_dates,
    render_qmt_bars_export,
    render_qmt_strategy,
    stage_qmt_strategy,
    universe_changes,
)
from quant.spec import SpecError, parse_spec  # noqa: E402


def _assets(snapshot: str) -> list[str]:
    path = os.path.join(snapshot, "manifest.json")
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    assets = manifest.get("assets") or []
    if not assets:
        raise SystemExit(f"{snapshot} 的 manifest 没有 assets")
    return list(assets)


def _read_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    import csv

    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _asset_dates(snapshot: str) -> dict[str, str]:
    """从快照 prices.csv 取每个标的第一条行情日期，作为上市/可用起点。"""
    first: dict[str, str] = {}
    for row in _read_rows(os.path.join(snapshot, "prices.csv")):
        asset = row.get("asset")
        day = row.get("date")
        if asset and day and (asset not in first or day < first[asset]):
            first[asset] = day
    return first


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 QMT 内置策略文件（不启动/不下单）")
    ap.add_argument("--spec", required=True, help="内部 spec JSON")
    ap.add_argument("--snapshot", help="从该快照 manifest 取 assets")
    ap.add_argument("--assets", help="逗号分隔的资产列表（覆盖 --snapshot）")
    ap.add_argument("--account", default=None, help="QMT 资金账号；默认读 config/qmt.json")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="QMT 账户配置路径")
    ap.add_argument("--name", default="nfr_strategy")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "output", "qmt"))
    ap.add_argument("--qmt-dir", help="QMT 的 python 目录；默认读 config/qmt.json")
    ap.add_argument("--no-qmt-copy", action="store_true", help="只写 output/qmt，不复制到 QMT 目录")
    ap.add_argument("--export-nav", help="QMT 回测时写日频净值的 CSV 路径")
    ap.add_argument("--no-nav-export", action="store_true", help="不生成净值导出代码")
    ap.add_argument("--export-bars", action="store_true", help="另生成只导出 QMT 日线 close 的策略")
    ap.add_argument("--bars-out", help="QMT 日线 CSV 输出路径")
    ap.add_argument("--paper", action="store_true", help="生成前向模拟盘版本：动态月度调仓、追加 NAV")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    config_path = os.path.abspath(args.config)
    cfg = load_account_config(config_path)
    account = args.account or str(cfg.get("account_id") or "").strip()
    if not account:
        account = "YOUR_ACCOUNT_ID"
        print(f"WARN: {config_path} 没有 account_id，生成文件仍是占位符", file=sys.stderr)
    qmt_dir = None if args.no_qmt_copy else (args.qmt_dir or cfg.get("qmt_python_dir"))
    nav_path = None
    if not args.no_nav_export:
        nav_path = args.export_nav or os.path.join(ROOT, "output", "qmt", args.name + "_nav.csv")
    print(f"account={account} config={config_path} qmt_dir={qmt_dir or '-'}")

    with open(args.spec, encoding="utf-8-sig") as fh:
        raw = json.load(fh)
    try:
        spec = parse_spec(raw)
    except SpecError as exc:
        print(f"spec 不合法：{exc}", file=sys.stderr)
        return 2
    if args.assets:
        assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    elif args.snapshot:
        assets = _assets(args.snapshot)
    else:
        print("给 --snapshot 或 --assets", file=sys.stderr)
        return 2
    first_dates = _asset_dates(args.snapshot) if args.snapshot else {}
    uni_changes = universe_changes(_read_rows(os.path.join(args.snapshot, "universe.csv"))) if args.snapshot else []
    calendar = [r["date"] for r in _read_rows(os.path.join(args.snapshot, "calendar.csv"))] if args.snapshot else []
    reb_dates = rebalance_dates(calendar, spec.start, spec.end, spec.rebalance) if calendar else []
    print(f"universe_changes={len(uni_changes)} rebalance_dates={len(reb_dates)}")

    bars_csv = args.bars_out or os.path.join(ROOT, "output", "qmt", "qmt_bars.csv")
    bars_source_path = os.path.join(ROOT, "output", "qmt", "nfr_bars_export.py")
    if args.export_bars:
        bars_source = render_qmt_bars_export(assets, bars_csv)
        if not args.dry_run:
            with open(bars_source_path, "w", encoding="gbk", errors="replace", newline="\n") as fh:
                fh.write(bars_source)
            if qmt_dir:
                os.makedirs(qmt_dir, exist_ok=True)
                with open(os.path.join(qmt_dir, "nfr_bars_export.py"), "w", encoding="gbk", errors="replace", newline="\n") as fh:
                    fh.write(bars_source)
        print(f"bars export strategy: {bars_source_path} -> {bars_csv}")

    try:
        if args.dry_run:
            source = render_qmt_strategy(
                spec,
                assets,
                account_id=account,
                name=args.name,
                config_path=config_path,
                asset_first_dates=first_dates,
                universe_changes=uni_changes,
                rebalance_dates=reb_dates,
                nav_path=nav_path,
                paper=args.paper,
            )
            print(source[:4000])
            print(f"\n[dry-run] {len(source)} chars, {len(assets)} assets; 未写盘")
            return 0
        result = stage_qmt_strategy(
            spec,
            assets,
            account_id=account,
            out_dir=args.out_dir,
            qmt_python_dir=qmt_dir,
            name=args.name,
            force=args.force,
            config_path=config_path,
            asset_first_dates=first_dates,
            universe_changes=uni_changes,
            rebalance_dates=reb_dates,
            nav_path=nav_path,
            paper=args.paper,
        )
    except QmtDeployError as exc:
        print(f"部署失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n下一步（人工）：")
    print("  1) QMT 客户端 -> 模型研究/我的策略 -> 新建 Python 策略")
    print("  2) 打开生成的 .py（GBK），全选复制，粘贴到 QMT 策略编辑器")
    print("  3) 账户号来自 config/qmt.json；改配置后重启策略（生成文件里有 fallback）")
    print("  注意：QMT 的“导入公式”只接受 .rzrk（QMT 自己导出的加密文件），不能导入 .py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
