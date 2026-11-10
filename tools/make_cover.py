"""生成一张纯色占位封面（不依赖 Pillow，只用 zlib + struct 写 PNG）。

    python tools/make_cover.py --out output/articles/cover-placeholder.png

产物用于 draft/add 的 thumb_media_id：草稿必须有封面，但正式封面应由人来定。
"""

from __future__ import annotations

import argparse
import os
import struct
import zlib

BG = (25, 24, 23)       # 近黑，偏暖
ACCENT = (192, 174, 140)  # 米色，仿宣纸
FRAME = (58, 54, 48)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: str, width: int, height: int, rows: list[bytearray]) -> None:
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit, color type 2 (RGB)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def make(width: int = 900, height: int = 383) -> list[bytearray]:
    rows = [bytearray(BG * width) for _ in range(height)]

    def put(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            rows[y][x * 3 : x * 3 + 3] = bytes(color)

    def hline(x0: int, x1: int, y: int, color, thickness: int = 1) -> None:
        for t in range(thickness):
            for x in range(x0, x1):
                put(x, y + t, color)

    def vline(x: int, y0: int, y1: int, color, thickness: int = 1) -> None:
        for t in range(thickness):
            for y in range(y0, y1):
                put(x + t, y, color)

    margin = int(width * 0.08)
    # 内嵌细边框，让纯色块看起来像有设计，而不是上传失败
    hline(margin, width - margin, margin, FRAME)
    hline(margin, width - margin, height - margin - 1, FRAME)
    vline(margin, margin, height - margin, FRAME)
    vline(width - margin - 1, margin, height - margin, FRAME)

    # 左下角一条短横线，作为唯一的视觉锚点
    y = int(height * 0.70)
    hline(margin * 2, margin * 2 + int(width * 0.22), y, ACCENT, thickness=3)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output/articles/cover-placeholder.png")
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--height", type=int, default=383)
    args = ap.parse_args()

    path = args.out if os.path.isabs(args.out) else os.path.join(os.getcwd(), args.out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_png(path, args.width, args.height, make(args.width, args.height))
    print(f"wrote {path} ({os.path.getsize(path)} bytes, {args.width}x{args.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
