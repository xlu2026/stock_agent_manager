"""内置策略注册入口。导入本包即完成注册。"""
from __future__ import annotations

from .base import REGISTRY, StrategyError, StrategyInfo, get, ids, register, validate_params

from . import composite, momentum_param, single_factor  # noqa: F401  (触发注册)

__all__ = ["REGISTRY", "StrategyError", "StrategyInfo", "get", "ids", "register", "validate_params"]
