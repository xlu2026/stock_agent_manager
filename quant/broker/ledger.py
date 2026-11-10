"""订单审计账本：每笔订单一行 JSONL，只追加，不修改。

对应 AGENTS.md B 节第 4 条：时间、标的、方向、数量、价格、来源实验 ID、人工确认标记。
真实券商通道接进来时，这个账本仍然由本项目写——不依赖券商那边的对账单。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .base import OrderRecord

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ledger_dir() -> str:
    """账本目录；测试可用 NFR_BROKER_DIR 指到临时目录。"""
    return os.environ.get("NFR_BROKER_DIR") or os.path.join(ROOT, "output", "broker")


def ledger_path(name: str = "orders") -> str:
    return os.path.join(ledger_dir(), f"{name}.jsonl")


def append(record: OrderRecord, name: str = "orders") -> str:
    os.makedirs(ledger_dir(), exist_ok=True)
    path = ledger_path(name)
    line = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path


def read_all(name: str = "orders") -> list[dict]:
    path = ledger_path(name)
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
