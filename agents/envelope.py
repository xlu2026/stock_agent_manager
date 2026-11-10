"""Agent 输出的统一信封。

Phase 1 不做 Router，但两个 Agent 的产物必须能被同一种结构消费，
否则 Phase 2 的"回测完成 -> 触发草稿"只能靠模型猜字段。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

ENVELOPE_SCHEMA = "nerve.envelope/v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel(path: str) -> str:
    """对外只暴露仓库相对路径，便于另一个 Agent 直接解析。"""
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path


def envelope(
    *,
    agent: str,
    kind: str,
    status: str,
    id_: str,
    summary: dict,
    artifacts: list[dict] | None = None,
    compliance: dict | None = None,
    error: str | None = None,
) -> dict:
    body = {
        "schema": ENVELOPE_SCHEMA,
        "agent": agent,
        "kind": kind,
        "status": status,
        "id": id_,
        "created_utc": utc_now(),
        "summary": summary,
        "artifacts": artifacts or [],
        "compliance": compliance or {"checked": False, "violations": []},
    }
    if error:
        body["error"] = error
    return body


def write_json(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    return path
