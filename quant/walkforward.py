"""滚动 walk-forward 的折划分与网格。"""
from __future__ import annotations


def _first_last(calendar: list[str], year: int) -> tuple[str, str] | None:
    days = [d for d in calendar if d.startswith(str(year))]
    return (days[0], days[-1]) if days else None


def make_folds(
    calendar: list[str],
    train_start: str = "2020-03-02",
    first_test_year: int = 2023,
    last_test_year: int = 2026,
) -> list[dict]:
    """每年一折：训练 = 前 3 个日历年，测试 = 当年；首折训练起点受预热约束。"""
    folds = []
    for year in range(first_test_year, last_test_year + 1):
        train_begin = _first_last(calendar, year - 3)
        train_end = _first_last(calendar, year - 1)
        test = _first_last(calendar, year)
        if not train_begin or not train_end or not test:
            continue
        train_start_actual = max(train_start, train_begin[0])
        if train_start_actual >= train_end[1]:
            continue
        folds.append(
            {
                "test_year": year,
                "train_start": train_start_actual,
                "train_end": train_end[1],
                "test_start": test[0],
                "test_end": test[1],
            }
        )
    return folds


def grid_specs(
    fold: dict,
    top_k_values=(5, 8, 10),
    weights=((0.5, 0.5), (0.7, 0.3), (0.3, 0.7)),
    weighting: str = "equal",
) -> list[dict]:
    specs = []
    for momentum, lowvol in weights:
        for top_k in top_k_values:
            specs.append(
                {
                    "strategy": "composite",
                    "params": {
                        "factors": {"momentum_12_1": momentum, "low_vol_60d": lowvol}
                    },
                    "universe": "hs300_40_pit",
                    "start": fold["train_start"],
                    "end": fold["train_end"],
                    "rebalance": "M",
                    "top_k": top_k,
                    "weighting": weighting,
                    "cost_bps": 10,
                    "seed": 42,
                }
            )
    return specs


def test_spec(fold: dict, params: dict, top_k: int, weighting: str = "equal") -> dict:
    return {
        "strategy": "composite",
        "params": {"factors": params},
        "universe": "hs300_40_pit",
        "start": fold["test_start"],
        "end": fold["test_end"],
        "rebalance": "M",
        "top_k": top_k,
        "weighting": weighting,
        "cost_bps": 10,
        "seed": 42,
    }


def fixed_spec(fold: dict, weighting: str = "equal") -> dict:
    return test_spec(fold, {"momentum_12_1": 0.5, "low_vol_60d": 0.5}, 8, weighting)


def baseline_spec(fold: dict) -> dict:
    return {
        "strategy": "single_factor",
        "params": {"factor": "momentum_12_1"},
        "universe": "hs300_40_pit",
        "start": fold["test_start"],
        "end": fold["test_end"],
        "rebalance": "M",
        "top_k": 8,
        "weighting": "equal",
        "cost_bps": 10,
        "seed": 42,
    }
