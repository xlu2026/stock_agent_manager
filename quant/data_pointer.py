"""最新快照指针：Agent 2 刷新成功后写，Agent 1 用 `--latest` 读。

指针只是“最后一次成功快照”的快捷方式，不是数据本身；文件在 ``output/data/latest.json``。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINTER_ENV = "NFR_LATEST_POINTER"
SCHEMA = "nerve.snapshot-pointer/v1"


def pointer_path() -> str:
    return os.environ.get(POINTER_ENV) or os.path.join(ROOT, "output", "data", "latest.json")


def _atomic_write(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def write_pointer(snapshot_dir: str, job_id: str | None = None) -> dict:
    manifest_path = os.path.join(snapshot_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"快照没有 manifest.json：{snapshot_dir}")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    sha = str(manifest.get("sha256") or "")
    if not sha and not manifest.get("data_version"):
        raise ValueError(f"快照 manifest 缺少 sha256/data_version：{manifest_path}")
    notes = manifest.get("notes") or {}
    payload = {
        "schema": SCHEMA,
        "data_version": manifest.get("data_version") or ("dv-" + sha[:12]),
        "dir": os.path.abspath(snapshot_dir),
        "universe": manifest.get("universe"),
        "start": manifest.get("start"),
        "end": manifest.get("end"),
        "assets": len(manifest.get("assets") or []),
        "source": manifest.get("source"),
        "point_in_time": bool(notes.get("universe_point_in_time")),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "job_id": job_id,
    }
    _atomic_write(pointer_path(), payload)
    return payload


def read_pointer() -> dict:
    path = pointer_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"没有最新快照指针：{path}。先让 Agent 2 成功刷新一次，或用 --data-dir 直接指定"
        )
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("schema") != SCHEMA or not payload.get("dir"):
        raise ValueError(f"快照指针格式不对：{path}")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="写入/查看最新快照指针")
    ap.add_argument("--dir", help="快照目录（写入时必需）")
    ap.add_argument("--job-id")
    ap.add_argument("--show", action="store_true", help="只打印当前指针")
    args = ap.parse_args(argv)
    if args.show or not args.dir:
        print(json.dumps(read_pointer(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(write_pointer(args.dir, args.job_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
