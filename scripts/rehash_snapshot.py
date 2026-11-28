"""给已有快照补齐全文件 snapshot_sha256/data_version（不重算数据）。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from quant.providers.contract import snapshot_digest  # noqa: E402


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rehash(directory: str) -> dict:
    path = os.path.join(directory, "manifest.json")
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    names = [n for n in ("prices.csv", "calendar.csv", "fundamentals.csv", "universe.csv") if os.path.exists(os.path.join(directory, n))]
    files = {}
    for name in names:
        with open(os.path.join(directory, name), encoding="utf-8-sig", newline="") as fh:
            rows = sum(1 for _ in csv.DictReader(fh))
        files[name] = {"sha256": _sha256(os.path.join(directory, name)), "rows": rows}
    digest = snapshot_digest(files, int(manifest.get("schema_version") or 2), str(manifest.get("universe") or ""), str(manifest.get("adjust_mode") or "none"))
    manifest["files"] = files
    manifest["snapshot_sha256"] = digest
    manifest["data_version"] = "dv-" + digest[:12]
    manifest["sha256"] = files["prices.csv"]["sha256"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return {"dir": os.path.abspath(directory), "data_version": manifest["data_version"], "snapshot_sha256": digest}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="重算快照的全文件 data_version")
    ap.add_argument("snapshot")
    args = ap.parse_args(argv)
    print(json.dumps(rehash(args.snapshot), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
