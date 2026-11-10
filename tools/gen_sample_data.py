"""生成确定性合成样本数据（quant/data/prices.csv + manifest.json）。

只在需要重建数据快照时运行：
    python tools/gen_sample_data.py

同一 seed / 同一 Python 主版本的 ``random.Random`` 序列稳定，因此产物逐位可复现；
CSV 写完后计算的 sha256 就是数据版本 ``data_version``。
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
from datetime import date, timedelta

SEED = 20240101
N_ASSETS = 40
START = date(2019, 1, 2)
END = date(2024, 12, 31)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quant", "data")
CSV_PATH = os.path.join(OUT_DIR, "prices.csv")
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")

# 过程参数：保证动量、价值、质量三类信号都有可检出的弱预测力
PHI_TREND = 0.985          # 趋势持续性（动量来源）
SIG_TREND = 0.00055
KAPPA_GAP = 0.0025         # 估值缺口的均值回复速度（价值来源）
SIG_IDIO = 0.0110
MKT_LOADING = 0.60


def trading_days() -> list[str]:
    """工作日日历（不含节假日调整），仅用于合成数据。"""
    out: list[str] = []
    d = START
    while d <= END:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def gen_rows() -> tuple[list[str], list[str], list[dict]]:
    rng = random.Random(SEED)
    dates = trading_days()
    assets = [f"SYN{i:03d}" for i in range(1, N_ASSETS + 1)]

    # 每只资产的静态画像
    prof = {}
    for a in assets:
        q = rng.uniform(0.15, 1.0)                       # 质量
        prof[a] = {
            "quality": q,
            "mu": 0.010 + 0.045 * q,                     # 年化漂移（质量溢价）
            "multiple": rng.uniform(8.0, 20.0),          # 估值倍数
            "book0": rng.uniform(6.0, 18.0),
            "g_book": (0.015 + 0.075 * q) / 252.0,       # 账面年增速
            "roe0": 0.05 + 0.15 * q,
        }

    mkt = [rng.gauss(0.0, 0.004) for _ in dates]

    state = {a: {"trend": 0.0, "gap": 0.0, "book": prof[a]["book0"], "eta": 0.0} for a in assets}
    rows: list[dict] = []

    for i, d in enumerate(dates):
        for a in assets:
            p = prof[a]
            s = state[a]
            s["trend"] = PHI_TREND * s["trend"] + rng.gauss(0.0, SIG_TREND)
            daily_mu = p["mu"] / 252.0
            r = daily_mu + s["trend"] - KAPPA_GAP * s["gap"] + MKT_LOADING * mkt[i] + rng.gauss(0.0, SIG_IDIO)

            s["book"] *= math.exp(p["g_book"] + rng.gauss(0.0, 0.0004))
            s["gap"] += r - p["g_book"]

            close = s["book"] * p["multiple"] * math.exp(s["gap"])
            overnight = rng.gauss(0.0, 0.004)
            open_ = close * math.exp(-r + overnight)  # 近似上一收盘 + 隔夜跳空
            spread = abs(rng.gauss(0.0, 0.006))
            high = max(open_, close) * (1.0 + spread)
            low = min(open_, close) * (1.0 - spread)
            volume = math.exp(rng.gauss(math.log(2.0e6), 0.45))

            s["eta"] = 0.97 * s["eta"] + rng.gauss(0.0, 0.06)
            roe = p["roe0"] * math.exp(s["eta"])
            earnings = s["book"] * roe

            rows.append(
                {
                    "date": d,
                    "asset": a,
                    "open": round(open_, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": int(volume),
                    "book": round(s["book"], 4),
                    "earnings": round(earnings, 4),
                }
            )
    return dates, assets, rows


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    dates, assets, rows = gen_rows()
    cols = ["date", "asset", "open", "high", "low", "close", "volume", "book", "earnings"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    h = hashlib.sha256()
    with open(CSV_PATH, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()

    manifest = {
        "schema_version": 1,
        "universe": "synthetic_40",
        "generator": "tools/gen_sample_data.py",
        "seed": SEED,
        "calendar": "weekdays",
        "start": dates[0],
        "end": dates[-1],
        "rows": len(rows),
        "assets": assets,
        "sha256": digest,
        "note": "合成样本数据，非真实行情；仅用于验证回测链路。",
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"wrote {CSV_PATH}")
    print(f"rows={len(rows)} dates={len(dates)} assets={len(assets)}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
