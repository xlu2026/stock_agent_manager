"""命令行入口：``srq`` 的等价实现。

    python -m quant.cli mcp serve
    python -m quant.cli validate --spec-file research.json
    python -m quant.cli backtest --spec-file research.json
    python -m quant.cli experiments list
    python -m quant.cli experiments get exp-xxxxxxxxxxxx
    python -m quant.cli doctor

所有子命令把结构化 JSON 打到 stdout，便于 Agent 与脚本消费。
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import experiments as exp_store
from .data import data_dir_path, load_panel
from .engine import ENGINE_VERSION, run_backtest, run_factor_analysis
from .paper import run_paper_session
from .spec import FACTORS, REBALANCE, SpecError, parse_spec
from .validate import validate_strategy


def _force_utf8() -> None:
    from .console import force_utf8

    force_utf8()


def _read_spec(args) -> dict:
    if args.spec_file:
        # utf-8-sig：Windows 上用 Out-File / 记事本保存的 JSON 常带 BOM
        with open(args.spec_file, encoding="utf-8-sig") as fh:
            return json.load(fh)
    if args.spec:
        return json.loads(args.spec)
    raise SystemExit("需要 --spec 或 --spec-file")


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_mcp(args) -> int:
    if args.action != "serve":
        raise SystemExit("用法：mcp serve")
    from .mcp_server import serve

    return serve()


def cmd_research(args) -> int:
    """四字段研究指令入口：与 MCP 的 run_research_instruction 同一套映射。"""
    from .instruction import InstructionError, parse_instruction

    raw = _read_spec(args)
    try:
        ins = parse_instruction(raw)
    except InstructionError as exc:
        _emit({"ok": False, "code": exc.code, "message": str(exc), **exc.extra})
        return 3

    resolved = {
        "question": ins.question,
        "universe": ins.universe,
        "period": ins.period,
        "start": ins.start,
        "end": ins.end,
        "factor": ins.factor,
    }
    if args.dry_run:
        _emit({"ok": True, "mode": "dry-run", "resolved": resolved, "mapping": ins.mapping})
        return 0

    spec = parse_spec(ins.to_spec())
    bt = run_backtest(spec)
    rec = exp_store.save(bt)
    _emit(
        {
            "ok": True,
            "experiment_id": bt.experiment_id,
            "resolved": resolved,
            "mapping": ins.mapping,
            "metrics": bt.metrics,
            "data_version": bt.data_version,
            "runs": rec["runs"],
        }
    )
    return 0


def cmd_validate(args) -> int:
    _emit(validate_strategy(_read_spec(args)))
    return 0


def cmd_backtest(args) -> int:
    spec = parse_spec(_read_spec(args))
    bt = run_backtest(spec)
    rec = exp_store.save(bt)
    _emit(
        {
            "experiment_id": bt.experiment_id,
            "status": "completed",
            "spec": bt.spec.canonical(),
            "data_version": bt.data_version,
            "metrics": bt.metrics,
            "provenance": bt.provenance,
            "runs": rec["runs"],
            "record": f"experiments/{bt.experiment_id}.json",
        }
    )
    return 0


def cmd_factor(args) -> int:
    spec = parse_spec(_read_spec(args))
    _emit(run_factor_analysis(spec, args.quantiles))
    return 0


def cmd_paper(args) -> int:
    spec = parse_spec(_read_spec(args))
    _emit(run_paper_session(spec, args.sessions))
    return 0


def cmd_experiments(args) -> int:
    if args.action == "list":
        _emit(exp_store.list_experiments(args.limit))
    else:
        _emit(exp_store.get_experiment(args.experiment_id, args.series))
    return 0


def cmd_doctor(args) -> int:
    panel = load_panel()
    _emit(
        {
            "ok": True,
            "engine_version": ENGINE_VERSION,
            "quant_version": __version__,
            "python": sys.version.split()[0],
            "server": "srq-compat (MCP stdio)",
            "data": {
                "version": panel.data_version,
                "assets": len(panel.assets),
                "dates": len(panel.dates),
                "start": panel.dates[0],
                "end": panel.dates[-1],
                "source": panel.source,
                "provider": panel.provider,
                "schema_version": panel.schema_version,
                "adjust_mode": panel.adjust_mode,
                "filled_rows": panel.filled_rows,
                "point_in_time_universe": panel.has_point_in_time_universe(),
                "dir": data_dir_path(),
            },
            "factors": sorted(FACTORS),
            "rebalance": sorted(REBALANCE),
            "live_trading": "unavailable_by_design",
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="srq", description="SolidRockQuant 兼容回测内核")
    p.add_argument("--version", action="version", version=f"srq-compat {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("mcp", help="MCP 相关操作")
    m.add_argument("action", choices=["serve"])
    m.set_defaults(func=cmd_mcp)

    for name, fn, extra in (
        ("validate", cmd_validate, None),
        ("backtest", cmd_backtest, None),
        ("research", cmd_research, None),
        ("factor", cmd_factor, None),
        ("paper", cmd_paper, None),
    ):
        sp = sub.add_parser(name)
        sp.add_argument("--spec")
        sp.add_argument("--spec-file")
        if name == "research":
            sp.add_argument("--dry-run", action="store_true", help="只做契约解析与因子映射，不回测")
        if name == "factor":
            sp.add_argument("--quantiles", type=int, default=5)
        if name == "paper":
            sp.add_argument("--sessions", type=int, default=6)
        sp.set_defaults(func=fn)

    e = sub.add_parser("experiments")
    e.add_argument("action", choices=["list", "get"])
    e.add_argument("experiment_id", nargs="?")
    e.add_argument("--limit", type=int, default=20)
    e.add_argument("--series", action="store_true")
    e.set_defaults(func=cmd_experiments)

    d = sub.add_parser("doctor")
    d.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SpecError as exc:
        print(json.dumps({"ok": False, "error": "SpecError", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
