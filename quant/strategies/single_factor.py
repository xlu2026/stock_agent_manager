"""单因子策略：兼容旧 spec 的 ``factor`` 字段。"""
from __future__ import annotations

from ..factors import FACTOR_FUNCS, MIN_HISTORY, scores
from .base import StrategyInfo, register

PARAMS_SCHEMA = {
    "type": "object",
    "properties": {"factor": {"type": "string", "enum": sorted(FACTOR_FUNCS)}},
    "required": ["factor"],
    "additionalProperties": False,
}


def _warmup(params: dict) -> int:
    return MIN_HISTORY[params["factor"]]


def _score(panel, i: int, params: dict) -> dict[str, float]:
    return scores(panel, params["factor"], i)


def _required(params: dict) -> tuple[str, ...]:
    if params["factor"] in ("value_proxy", "quality_proxy"):
        return ("price", "fundamentals")
    return ("price",)


register(
    StrategyInfo(
        id="single_factor",
        version="1.0",
        description="单因子截面排名：按一个已实现因子的得分排序，取 top_k 等权。",
        params_schema=PARAMS_SCHEMA,
        warmup=_warmup,
        score=_score,
        required_data=_required,
    )
)
