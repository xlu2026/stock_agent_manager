"""策略注册表：把"怎么打分"从引擎里拆出来。

策略只负责两件事：给定一个信号日 i 和参数，返回 {asset: score}；以及声明预热长度。
组合构造（top_k/权重）仍由引擎负责，后续再拆成独立的构造器。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..data import Panel


class StrategyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


@dataclass(frozen=True)
class StrategyInfo:
    id: str
    version: str
    description: str
    params_schema: dict[str, Any]
    warmup: Callable[[dict], int]
    score: Callable[[Panel, int, dict], dict[str, float]]
    check: Callable[[dict], None] | None = None
    required_data: Callable[[dict], tuple[str, ...]] = lambda _params: ("price",)


REGISTRY: dict[str, StrategyInfo] = {}


def register(info: StrategyInfo) -> None:
    if info.id in REGISTRY:
        raise RuntimeError(f"策略 {info.id} 重复注册")
    REGISTRY[info.id] = info


def get(strategy_id: str) -> StrategyInfo:
    try:
        return REGISTRY[strategy_id]
    except KeyError as exc:
        raise StrategyError(
            "UNKNOWN_STRATEGY",
            f"未知策略 {strategy_id!r}；可用：{sorted(REGISTRY)}",
        ) from exc


def ids() -> list[str]:
    return sorted(REGISTRY)


def _check_type(value: Any, expected: str, name: str) -> None:
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是整数，收到 {value!r}")
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是数字，收到 {value!r}")
    elif expected == "string":
        if not isinstance(value, str):
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是字符串，收到 {value!r}")
    elif expected == "object":
        if not isinstance(value, dict):
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是对象，收到 {value!r}")
    elif expected == "array":
        if not isinstance(value, list):
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是数组，收到 {value!r}")


def validate_params(strategy_id: str, raw: Any) -> dict:
    """按策略的 params_schema 做最小 JSON Schema 校验，并补默认值。"""
    info = get(strategy_id)
    schema = info.params_schema
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StrategyError("BAD_PARAMS", f"策略 {strategy_id} 的 params 必须是对象")
    properties = schema.get("properties") or {}
    unknown = sorted(set(raw) - set(properties))
    if unknown:
        raise StrategyError("UNKNOWN_PARAM", f"策略 {strategy_id} 不认识参数 {unknown}；可用：{sorted(properties)}")

    out: dict[str, Any] = {}
    for name, prop in properties.items():
        if name in raw:
            value = raw[name]
        elif "default" in prop:
            value = prop["default"]
        elif name in (schema.get("required") or []):
            raise StrategyError("MISSING_PARAM", f"策略 {strategy_id} 缺少参数 {name}")
        else:
            continue
        _check_type(value, prop.get("type", "string"), name)
        if "enum" in prop and value not in prop["enum"]:
            raise StrategyError("BAD_PARAM", f"参数 {name} 必须是 {prop['enum']} 之一，收到 {value!r}")
        if prop.get("type") in ("integer", "number"):
            if "minimum" in prop and value < prop["minimum"]:
                raise StrategyError("BAD_PARAM", f"参数 {name} 不能小于 {prop['minimum']}")
            if "maximum" in prop and value > prop["maximum"]:
                raise StrategyError("BAD_PARAM", f"参数 {name} 不能大于 {prop['maximum']}")
        out[name] = value
    if info.check:
        info.check(out)
    return out
