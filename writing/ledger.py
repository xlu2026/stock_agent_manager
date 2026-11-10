"""草稿账本：每次推送追加一行，免得到处手抄 media_id。

账本只追加不覆盖，`drafts.jsonl` 就是"这篇文章什么时候被推到哪个草稿"的唯一来源；
docs 里那张资产表退化成给人看的摘要，不再当权威。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "output", "reports", "drafts.jsonl")


def append(entry: dict, path: str | None = None) -> str:
    """追加一条记录，返回账本路径。"""
    path = path or LEDGER
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record = dict(entry)
    record.setdefault("ts", datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_all(path: str | None = None) -> list[dict]:
    path = path or LEDGER
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def latest_by_slug(entries: list[dict] | None = None) -> dict[str, dict]:
    """每个 slug 只留最后一条，用于回答"这篇现在在哪个草稿"。"""
    result: dict[str, dict] = {}
    for item in entries if entries is not None else read_all():
        slug = item.get("slug")
        if slug:
            result[slug] = item
    return result


def record_compliance(slug: str, payload: dict, path: str | None = None) -> str:
    """把一次合规检查落盘，文件名带 slug，便于事后复查。"""
    out_dir = os.path.dirname(path or LEDGER)
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"compliance-{slug}.json")
    body = dict(payload)
    body.setdefault("checked_at", datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target
