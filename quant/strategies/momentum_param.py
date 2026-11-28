"""参数化动量：lookback / skip 可调，用来验证参数扫描接口。"""
from __future__ import annotations

from .base import StrategyError, StrategyInfo, register

PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "lookback": {"type": "integer", "minimum": 20, "maximum": 500, "default": 252},
        "skip": {"type": "integer", "minimum": 0, "maximum": 120, "default": 21},
    },
    "additionalProperties": False,
}


def _check(params: dict) -> None:
    if params["skip"] >= params["lookback"]:
        raise StrategyError("BAD_PARAM", "skip 必须小于 lookback")


def _warmup(params: dict) -> int:
    return int(params["lookback"])


def _score(panel, i: int, params: dict) -> dict[str, float]:
    lookback = int(params["lookback"])
    skip = int(params["skip"])
    if i < lookback:
        return {}
    out: dict[str, float] = {}
    for asset in panel.assets:
        start = panel.close[asset][i - lookback]
        end = panel.close[asset][i - skip]
        if start > 0:
            out[asset] = end / start - 1.0
    return out


register(
    StrategyInfo(
        id="momentum_param",
        version="1.0",
        description="参数化动量：t-lookback 到 t-skip 的累计收益，跳过最近 skip 天。",
        params_schema=PARAMS_SCHEMA,
        warmup=_warmup,
        score=_score,
        check=_check,
    )
)
