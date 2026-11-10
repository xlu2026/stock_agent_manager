"""Read an Electron asar archive with the standard library only.

Usage:
  python tools/asar_tool.py ls  <asar> [substring]
  python tools/asar_tool.py cat <asar> <internal/path>
"""
from __future__ import annotations

import json
import struct
import sys


class Asar:
    def __init__(self, path: str) -> None:
        self.path = path
        with open(path, "rb") as fh:
            head = fh.read(16)
            _size, header_size, _json_size, json_len = struct.unpack("<IIII", head)
            raw = fh.read(json_len)
        self.index = json.loads(raw.decode("utf-8"))
        self.base = 16 + json_len

    def ls(self, needle: str = "") -> list[str]:
        out: list[str] = []

        def walk(node: dict, prefix: str) -> None:
            for name, entry in node.get("files", {}).items():
                full = f"{prefix}/{name}" if prefix else name
                if "files" in entry:
                    walk(entry, full)
                elif needle.lower() in full.lower():
                    out.append(full)

        walk(self.index, "")
        return sorted(out)

    def entry(self, internal: str) -> dict:
        node = self.index
        for part in internal.split("/"):
            node = node["files"][part]
        return node

    def read(self, internal: str) -> bytes:
        e = self.entry(internal)
        with open(self.path, "rb") as fh:
            fh.seek(self.base + int(e["offset"]))
            return fh.read(int(e["size"]))


def main(argv: list[str]) -> int:
    cmd, asar_path = argv[1], argv[2]
    a = Asar(asar_path)
    if cmd == "ls":
        needle = argv[3] if len(argv) > 3 else ""
        for p in a.ls(needle):
            print(p)
        return 0
    if cmd == "cat":
        sys.stdout.write(a.read(argv[3]).decode("utf-8", "replace"))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
