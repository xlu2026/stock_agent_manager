"""实验登记簿：每次回测落盘为一条可复查记录。

存储是纯文件（``experiments/<experiment_id>.json`` + ``experiments/index.jsonl``），
不引入数据库；写盘用临时文件 + 原子替换，避免半截文件。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .engine import Backtest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def exp_dir() -> str:
    """实验目录；测试可用 NFR_EXPERIMENTS_DIR 指到临时目录，避免污染真实记录。"""
    return os.environ.get("NFR_EXPERIMENTS_DIR") or os.path.join(ROOT, "experiments")


def index_path() -> str:
    return os.path.join(exp_dir(), "index.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _private_dir() -> str:
    return os.path.join(exp_dir(), ".private")


def _split_holdings(holdings: list[dict]) -> tuple[list[dict], list[dict]]:
    """公开记录里去掉个股代码，代码只留在 .private/ 下。"""
    public, private = [], []
    for row in holdings or []:
        names = row.get("names") or []
        public.append({k: v for k, v in row.items() if k != "names"})
        private.append({"date": row.get("date"), "names": names})
    return public, private


def _write_private(experiment_id: str, holdings: list[dict], now: str) -> str | None:
    if not holdings:
        return None
    os.makedirs(_private_dir(), exist_ok=True)
    path = os.path.join(_private_dir(), f"{experiment_id}.json")
    payload = {
        "experiment_id": experiment_id,
        "written_utc": now,
        "note": "仅内部使用：含个股代码，不得进入公开输出",
        "holdings": holdings,
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def save(bt: Backtest) -> dict:
    os.makedirs(exp_dir(), exist_ok=True)
    path = os.path.join(exp_dir(), f"{bt.experiment_id}.json")
    now = _now()

    existing = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = json.load(fh)

    public_holdings, private_holdings = _split_holdings(bt.holdings)
    record = {
        "experiment_id": bt.experiment_id,
        "first_recorded_utc": existing["first_recorded_utc"] if existing else now,
        "last_run_utc": now,
        "runs": (existing["runs"] + 1) if existing else 1,
        "status": "completed",
        "spec": bt.spec.canonical(),
        "data_version": bt.data_version,
        "metrics": bt.metrics,
        "provenance": bt.provenance,
        "rebalance_days": bt.rebalance_days,
        "holdings": public_holdings,
        "holdings_redacted": True,
        "nav_series": {"dates": bt.dates, "nav": bt.nav},
        "benchmark_series": {"dates": bt.dates, "nav": bt.benchmark_nav},
    }
    _atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    _write_private(bt.experiment_id, private_holdings, now)

    if not existing:
        with open(index_path(), "a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "experiment_id": bt.experiment_id,
                        "recorded_utc": now,
                        "factor": bt.spec.factor,
                        "strategy": bt.spec.strategy,
                        "params": bt.spec.params,
                        "window": f"{bt.spec.start}..{bt.spec.end}",
                        "cagr": bt.metrics["cagr"],
                        "sharpe": bt.metrics["sharpe"],
                        "nav_hash": bt.metrics["nav_hash"],
                        "data_version": bt.data_version,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return record


def list_experiments(limit: int = 20) -> dict:
    if not os.path.exists(index_path()):
        return {"count": 0, "experiments": []}
    rows = []
    # utf-8-sig：仓库里的 jsonl 可能被 Windows 工具改写成带 BOM 的形式
    with open(index_path(), encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.reverse()
    return {"count": len(rows), "experiments": rows[: max(1, min(limit, 200))]}


def get_experiment(experiment_id: str, include_series: bool = True) -> dict:
    if not experiment_id.startswith("exp-") or "/" in experiment_id or ".." in experiment_id:
        raise ValueError(f"非法 experiment_id {experiment_id!r}")
    path = os.path.join(exp_dir(), f"{experiment_id}.json")
    if not os.path.exists(path):
        raise KeyError(f"实验 {experiment_id} 不存在；先用 list_experiments 查看已登记的实验")
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    if not include_series:
        rec.pop("nav_series", None)
        rec.pop("benchmark_series", None)
        rec.pop("holdings", None)
    return rec


def get_experiment_holdings(experiment_id: str, date: str | None = None) -> dict:
    """读取内部持仓明细（含个股代码）。只给 Agent 1 做订单草案用，不得对外。"""
    if not experiment_id.startswith("exp-") or "/" in experiment_id or ".." in experiment_id:
        raise ValueError(f"非法 experiment_id {experiment_id!r}")
    path = os.path.join(_private_dir(), f"{experiment_id}.json")
    if not os.path.exists(path):
        raise KeyError(
            f"{experiment_id} 没有内部持仓明细；可能是脱敏前的旧记录，"
            "或者该实验没有持仓"
        )
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    rows = payload.get("holdings") or []
    if date:
        rows = [r for r in rows if r.get("date") == date]
        if not rows:
            raise KeyError(f"{experiment_id} 在 {date} 没有持仓记录")
    return {
        "experiment_id": experiment_id,
        "note": payload.get("note") or "仅内部使用：含个股代码，不得进入公开输出",
        "count": len(rows),
        "holdings": rows,
    }
