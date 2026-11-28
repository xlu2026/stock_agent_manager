"""把 Spec 渲染成 QMT 内置 Python 策略，并投递到 QMT 的 python 目录。

边界：
- 只生成/复制 `.py` 文件，**不启动策略、不登录、不下单**；
- QMT 策略的注册和自动运行在客户端内部，本模块没有公开 API 可调用；
- 生成的策略默认把账户号写成占位符，staging 时必须显式给 --account。

支持范围（2026-11-28）：
- single_factor：momentum_12_1 / low_vol_60d（纯价格）；
- momentum_param；
- composite：上述价格因子的 z-score 加权；
- weighting：equal / score / inverse_vol。
value/quality 需要 QMT 财务数据接口，当前未验证，拒绝生成而不是生成一个跑不通的策略。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone

from ..spec import Spec


class QmtDeployError(ValueError):
    pass


SUPPORTED_PRICE_FACTORS = {"momentum_12_1", "low_vol_60d"}
SUPPORTED_WEIGHTING = {"equal", "score", "inverse_vol"}
DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "qmt.json",
)


def load_account_config(path: str = DEFAULT_CONFIG) -> dict:
    """读 QMT 账户配置；account_id 为空时返回空 dict。"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise QmtDeployError(f"QMT 配置必须是 JSON 对象：{path}")
    return payload


def _strategy_factors(spec: Spec) -> tuple[list[str], dict[str, float]]:
    if spec.strategy == "single_factor":
        return [spec.factor], {spec.factor: 1.0}
    if spec.strategy == "momentum_param":
        return ["momentum_param"], {"momentum_param": 1.0}
    if spec.strategy == "composite":
        weights = dict(spec.params.get("factors") or {})
        return list(weights), {k: float(v) for k, v in weights.items()}
    raise QmtDeployError(f"QMT 渲染暂不支持策略 {spec.strategy!r}")


def _period_key(day: str, rebalance: str) -> tuple:
    d = date.fromisoformat(day)
    if rebalance == "M":
        return (d.year, d.month)
    if rebalance == "Q":
        return (d.year, (d.month - 1) // 3 + 1)
    iso = d.isocalendar()
    return (iso[0], iso[1])


def rebalance_dates(dates: list[str], start: str, end: str, rebalance: str) -> list[str]:
    """与引擎一致的调仓日：区间内每个周期的最后一个交易日。"""
    ordered = sorted(d for d in dates if start <= d <= end)
    out: list[str] = []
    last_key = None
    for day in ordered:
        key = _period_key(day, rebalance)
        if last_key is not None and key != last_key:
            out.append(prev)
        prev = day
        last_key = key
    if ordered:
        out.append(ordered[-1])
    return out


def universe_changes(rows: list[dict]) -> list[tuple[str, list[str]]]:
    """把 universe.csv 压成“生效日 -> 成分列表”，只在成分变化时记一条。"""
    by_date: dict[str, set[str]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        asset = str(row.get("asset") or "")
        if day and asset:
            by_date.setdefault(day, set()).add(asset)
    out: list[tuple[str, list[str]]] = []
    last: set[str] | None = None
    for day in sorted(by_date):
        members = by_date[day]
        if last is None or members != last:
            out.append((day, sorted(members)))
            last = members
    return out


def render_qmt_bars_export(assets: list[str], out_path: str, name: str = "nfr_bars_export") -> str:
    """生成只导出日线 close 的 QMT 策略；不交易。"""
    if not assets:
        raise QmtDeployError("assets 为空")
    lines = [
        "#coding:gbk",
        "# 自动生成：只导出 QMT 日线 close，不交易",
        "ASSETS = %r" % (list(assets),),
        "OUT_PATH = %r" % os.path.abspath(out_path),
        "",
        "def init(ContextInfo):",
        "    ContextInfo.set_universe(ASSETS)",
        "    try:",
        "        f = open(OUT_PATH, 'w', encoding='utf-8')",
        "        f.write('date,asset,close\\n')",
        "        f.close()",
        "    except Exception as exc:",
        "        print('bars export init failed: %s' % exc)",
        "",
        "",
        "def handlebar(ContextInfo):",
        "    d = ContextInfo.barpos",
        "    now = timetag_to_datetime(ContextInfo.get_bar_timetag(d), '%Y-%m-%d')",
        "    data = ContextInfo.get_history_data(1, '1d', 'close', 3)",
        "    try:",
        "        f = open(OUT_PATH, 'a', encoding='utf-8')",
        "        for asset in ASSETS:",
        "            series = data.get(asset) if hasattr(data, 'get') else None",
        "            if series and series[-1] is not None and series[-1] > 0:",
        "                f.write('%s,%s,%s\\n' % (now, asset, series[-1]))",
        "        f.close()",
        "    except Exception as exc:",
        "        print('bars export failed: %s' % exc)",
        "",
    ]
    return "\n".join(lines)


def _validate(spec: Spec) -> tuple[list[str], dict[str, float]]:
    if spec.weighting not in SUPPORTED_WEIGHTING:
        raise QmtDeployError(f"QMT 渲染暂不支持 weighting={spec.weighting!r}")
    if spec.rebalance not in {"M", "W", "Q"}:
        raise QmtDeployError(f"QMT 渲染暂不支持 rebalance={spec.rebalance!r}")
    factors, weights = _strategy_factors(spec)
    bad = sorted(set(factors) - SUPPORTED_PRICE_FACTORS - {"momentum_param"})
    if bad:
        raise QmtDeployError(
            f"QMT 渲染暂不支持因子 {bad}；value/quality 需要 QMT 财务数据接口，尚未验证"
        )
    if spec.strategy == "composite" and len(factors) < 2:
        raise QmtDeployError("composite 至少需要两个因子")
    return factors, weights


def _need(spec: Spec) -> int:
    if spec.strategy == "momentum_param":
        return int(spec.params["lookback"]) + int(spec.params["skip"]) + 3
    if spec.strategy == "composite":
        return 261
    return 261 if spec.factor == "momentum_12_1" else 63


def render_qmt_strategy(
    spec: Spec,
    assets: list[str],
    account_id: str = "YOUR_ACCOUNT_ID",
    name: str = "nfr_strategy",
    config_path: str | None = None,
    asset_first_dates: dict[str, str] | None = None,
    universe_changes: list[tuple[str, list[str]]] | None = None,
    rebalance_dates: list[str] | None = None,
    nav_path: str | None = None,
    paper: bool = False,
) -> str:
    """返回 QMT 策略源码（未落盘）。paper=True 时用动态月度调仓 + 追加 NAV。"""
    if not assets:
        raise QmtDeployError("assets 为空")
    config_path = os.path.abspath(config_path or DEFAULT_CONFIG)
    asset_first_dates = asset_first_dates or {}
    universe_changes = universe_changes or []
    rebalance_dates = [] if paper else (rebalance_dates or [])
    nav_path = os.path.abspath(nav_path) if nav_path else ""
    state_path = nav_path + ".state" if (paper and nav_path) else ""
    factors, weights = _validate(spec)
    payload = {
        "name": name,
        "strategy": spec.strategy,
        "params": spec.params,
        "factors": factors,
        "factor_weights": weights,
        "top_k": spec.top_k,
        "rebalance": spec.rebalance,
        "weighting": spec.weighting,
    }
    lines = [
        "#coding:gbk",
        "# 由 stock_agent_manager 生成：QMT 内置策略",
        "# 只生成文件，不自动启动；请在 QMT 客户端里手工导入/启动。",
        "import math",
        "import os",
        "",
        "ACCOUNT_ID = %r" % account_id,
        "CONFIG_PATH = %r" % config_path,
        "NAV_PATH = %r" % nav_path,
        "STATE_PATH = %r" % state_path,
        "PAPER = %r" % paper,
        "ASSETS = %r" % (list(assets),),
        "ASSET_FIRST = %r" % (asset_first_dates,),
        "UNIVERSE_CHANGES = %r" % (universe_changes,),
        "REBALANCE_DATES = %r" % (rebalance_dates,),
        "SPEC = %r" % (payload,),
        "FACTORS = %r" % (factors,),
        "FACTOR_WEIGHTS = %r" % (weights,),
        "TOP_K = %d" % spec.top_k,
        "REBALANCE = %r" % spec.rebalance,
        "WEIGHTING = %r" % spec.weighting,
        "NEED = %d" % _need(spec),
        "",
        "",
        "def _load_account():",
        "    try:",
        "        import json",
        "        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:",
        "            value = json.load(f).get('account_id')",
        "        if value:",
        "            return str(value)",
        "    except Exception:",
        "        pass",
        "    return ACCOUNT_ID",
        "",
        "",
        "def _members(now):",
        "    if not UNIVERSE_CHANGES:",
        "        return ASSETS",
        "    members = []",
        "    for effective, names in UNIVERSE_CHANGES:",
        "        if now >= effective:",
        "            members = names",
        "        else:",
        "            break",
        "    return members",
        "",
        "",
        "def init(ContextInfo):",
        "    ContextInfo.set_universe(ASSETS)",
        "    ContextInfo.accountID = _load_account()",
        "    ContextInfo._last_rebalance = None",
        "    ContextInfo._nav_seen = set()",
        "    if NAV_PATH:",
        "        try:",
        "            if PAPER and os.path.exists(NAV_PATH):",
        "                f = open(NAV_PATH, 'r', encoding='utf-8')",
        "                for line in f:",
        "                    parts = line.strip().split(',')",
        "                    if parts and parts[0] and parts[0] != 'date':",
        "                        ContextInfo._nav_seen.add(parts[0])",
        "                f.close()",
        "            else:",
        "                f = open(NAV_PATH, 'w', encoding='utf-8')",
        "                f.write('date,net_value\\n')",
        "                f.close()",
        "            if PAPER and STATE_PATH and os.path.exists(STATE_PATH):",
        "                f = open(STATE_PATH, 'r', encoding='utf-8')",
        "                ContextInfo._last_rebalance = f.read().strip()",
        "                f.close()",
        "        except Exception as exc:",
        "            print('NAV export init failed: %s' % exc)",
        "",
        "",
        "def _mean(xs):",
        "    return sum(xs) / float(len(xs)) if xs else 0.0",
        "",
        "",
        "def _valid(series, need):",
        "    if not series or len(series) < need:",
        "        return False",
        "    for value in series[-need:]:",
        "        try:",
        "            if value is None or value != value or value <= 0:",
        "                return False",
        "        except Exception:",
        "            return False",
        "    return True",
        "",
        "",
        "def _stdev(xs):",
        "    if len(xs) < 2:",
        "        return 0.0",
        "    mu = _mean(xs)",
        "    return math.sqrt(sum((x - mu) ** 2 for x in xs) / float(len(xs) - 1))",
        "",
        "",
        "def _returns(closes):",
        "    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]",
        "",
        "",
        "def _factor_value(factor, closes):",
        "    if factor == 'momentum_12_1':",
        "        if not _valid(closes, 253):",
        "            return None",
        "        return closes[-22] / closes[-253] - 1.0",
        "    if factor == 'momentum_param':",
        "        lookback = int(SPEC['params'].get('lookback', 252))",
        "        skip = int(SPEC['params'].get('skip', 21))",
        "        if not _valid(closes, lookback + 1):",
        "            return None",
        "        return closes[-1 - skip] / closes[-1 - lookback] - 1.0",
        "    if factor == 'low_vol_60d':",
        "        if not _valid(closes, 61):",
        "            return None",
        "        return -_stdev(_returns(closes[-61:]))",
        "    return None",
        "",
        "",
        "def _scores(closes_by_asset, now):",
        "    allowed = set(_members(now))",
        "    raw = {}",
        "    for factor in FACTORS:",
        "        vals = {}",
        "        for asset in ASSETS:",
        "            if allowed and asset not in allowed:",
        "                continue",
        "            first = ASSET_FIRST.get(asset)",
        "            if first and now < first:",
        "                continue",
        "            series = closes_by_asset.get(asset)",
        "            if not _valid(series, NEED):",
        "                continue",
        "            value = _factor_value(factor, series)",
        "            if value is not None:",
        "                vals[asset] = value",
        "        raw[factor] = vals",
        "    if len(FACTORS) == 1:",
        "        return raw[FACTORS[0]]",
        "    common = set(raw[FACTORS[0]])",
        "    for factor in FACTORS[1:]:",
        "        common &= set(raw[factor])",
        "    if not common:",
        "        return {}",
        "    zs = {}",
        "    for factor in FACTORS:",
        "        values = [raw[factor][a] for a in common]",
        "        mu = _mean(values)",
        "        sd = _stdev(values)",
        "        zs[factor] = {a: ((raw[factor][a] - mu) / sd if sd > 1e-12 else 0.0) for a in common}",
        "    total = sum(abs(FACTOR_WEIGHTS[f]) for f in FACTORS) or 1.0",
        "    out = {a: 0.0 for a in common}",
        "    for factor in FACTORS:",
        "        w = FACTOR_WEIGHTS[factor] / total",
        "        for a in common:",
        "            out[a] += w * zs[factor][a]",
        "    return out",
        "",
        "",
        "def _weights(picked, scores, closes_by_asset):",
        "    if WEIGHTING == 'equal':",
        "        return {a: 1.0 / len(picked) for a in picked}",
        "    if WEIGHTING == 'score':",
        "        low = min(scores[a] for a in picked)",
        "        raw = {a: scores[a] - low + 1e-9 for a in picked}",
        "        total = sum(raw.values()) or 1.0",
        "        return {a: raw[a] / total for a in picked}",
        "    raw = {}",
        "    for a in picked:",
        "        vol = _stdev(_returns(closes_by_asset[a][-61:]))",
        "        raw[a] = 1.0 / (vol if vol > 1e-6 else 0.02)",
        "    total = sum(raw.values()) or 1.0",
        "    w = {a: raw[a] / total for a in picked}",
        "    for _ in range(10):",
        "        over = {a: x - 0.25 for a, x in w.items() if x > 0.25 + 1e-12}",
        "        if not over:",
        "            break",
        "        excess = sum(over.values())",
        "        for a in over:",
        "            w[a] = 0.25",
        "        under = [a for a, x in w.items() if x < 0.25 - 1e-12]",
        "        pool = sum(w[a] for a in under)",
        "        if pool <= 0:",
        "            break",
        "        for a in under:",
        "            w[a] += excess * w[a] / pool",
        "    return w",
        "",
        "",
        "def _period_key(now):",
        "    if REBALANCE == 'M':",
        "        return now[:7]",
        "    if REBALANCE == 'Q':",
        "        return str((int(now[:4]), (int(now[5:7]) - 1) // 3 + 1))",
        "    return now[:4] + '-' + str((int(now[5:7]) - 1) // 7 + 1)",
        "",
        "",
        "def _holdings(account_id):",
        "    out = {}",
        "    for obj in get_trade_detail_data(account_id, 'STOCK', 'POSITION'):",
        "        code = obj.m_strInstrumentID + '.' + obj.m_strExchangeID",
        "        out[code] = obj.m_nVolume / 100",
        "    return out",
        "",
        "",
        "def _equity(ContextInfo, holdings, closes):",
        "    total = 0.0",
        "    for code, lots in holdings.items():",
        "        series = closes.get(code)",
        "        if series and series[-1] > 0:",
        "            total += lots * 100 * series[-1]",
        "    try:",
        "        for obj in get_trade_detail_data(ContextInfo.accountID, 'STOCK', 'ACCOUNT'):",
        "            for attr in ('m_dBalance', 'm_dTotalValue'):",
        "                value = getattr(obj, attr, None)",
        "                if value is not None and float(value) > 0:",
        "                    return float(value)",
        "    except Exception:",
        "        pass",
        "    return total if total > 0 else float(getattr(ContextInfo, 'capital', 0.0))",
        "",
        "",
        "def handlebar(ContextInfo):",
        "    d = ContextInfo.barpos",
        "    now = timetag_to_datetime(ContextInfo.get_bar_timetag(d), '%Y-%m-%d')",
        "    if NAV_PATH and now not in ContextInfo._nav_seen:",
        "        try:",
        "            value = ContextInfo.get_net_value(d)",
        "            with open(NAV_PATH, 'a', encoding='utf-8') as f:",
        "                f.write('%s,%s\\n' % (now, value))",
        "            ContextInfo._nav_seen.add(now)",
        "        except Exception as exc:",
        "            if not getattr(ContextInfo, '_nav_error', False):",
        "                print('NAV export failed: %s' % exc)",
        "                ContextInfo._nav_error = True",
        "    if REBALANCE_DATES:",
        "        if now not in REBALANCE_DATES:",
        "            return",
        "        if ContextInfo._last_rebalance == now:",
        "            return",
        "        ContextInfo._last_rebalance = now",
        "    else:",
        "        key = _period_key(now)",
        "        if ContextInfo._last_rebalance == key:",
        "            return",
        "        ContextInfo._last_rebalance = key",
        "    closes = ContextInfo.get_history_data(NEED + 2, '1d', 'close', 3)",
        "    # 信号只用当日之前的数据；当日价格只用于下单，避免用当日收盘选股再按当日收盘成交",
        "    signal_closes = {a: s[:-1] for a, s in closes.items() if s and len(s) > 1}",
        "    scores = _scores(signal_closes, now)",
        "    if len(scores) < TOP_K:",
        "        print('skip: scores=%d < top_k=%d' % (len(scores), TOP_K))",
        "        return",
        "    picked = sorted(scores, key=lambda a: (-scores[a], a))[:TOP_K]",
        "    target_w = _weights(picked, scores, signal_closes)",
        "    holdings = _holdings(ContextInfo.accountID)",
        "    account = ContextInfo.accountID",
        "    capital = _equity(ContextInfo, holdings, closes)",
        "    for code, lots in list(holdings.items()):",
        "        if code not in picked and lots > 0 and code in closes:",
        "            order_shares(code, -int(lots) * 100, 'fix', closes[code][-1], ContextInfo, account)",
        "    for code in picked:",
        "        price = closes[code][-1]",
        "        if price <= 0 or capital <= 0:",
        "            continue",
        "        target = int(target_w[code] * capital / price / 100) * 100",
        "        current = int(holdings.get(code, 0)) * 100",
        "        diff = target - current",
        "        if diff >= 100:",
        "            order_shares(code, diff, 'fix', price, ContextInfo, account)",
        "        elif diff <= -100:",
        "            order_shares(code, diff, 'fix', price, ContextInfo, account)",
        "    if PAPER and STATE_PATH:",
        "        try:",
        "            f = open(STATE_PATH, 'w', encoding='utf-8')",
        "            f.write(str(ContextInfo._last_rebalance))",
        "            f.close()",
        "        except Exception as exc:",
        "            print('state write failed: %s' % exc)",
        "    print('rebalance %s picked=%s' % (now, ','.join(picked)))",
        "",
    ]
    return "\n".join(lines)


def stage_qmt_strategy(
    spec: Spec,
    assets: list[str],
    account_id: str,
    out_dir: str,
    qmt_python_dir: str | None = None,
    name: str = "nfr_strategy",
    force: bool = False,
    config_path: str | None = None,
    asset_first_dates: dict[str, str] | None = None,
    universe_changes: list[tuple[str, list[str]]] | None = None,
    rebalance_dates: list[str] | None = None,
    nav_path: str | None = None,
    paper: bool = False,
) -> dict:
    source = render_qmt_strategy(
        spec,
        assets,
        account_id=account_id,
        name=name,
        config_path=config_path,
        asset_first_dates=asset_first_dates,
        universe_changes=universe_changes,
        rebalance_dates=rebalance_dates,
        nav_path=nav_path,
        paper=paper,
    )
    os.makedirs(out_dir, exist_ok=True)
    filename = name if name.endswith(".py") else name + ".py"
    path = os.path.join(out_dir, filename)
    if os.path.exists(path) and not force:
        raise QmtDeployError(f"目标已存在，拒绝覆盖：{path}（--force 可覆盖）")
    with open(path, "w", encoding="gbk", errors="replace", newline="\n") as fh:
        fh.write(source)
    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": name,
        "path": os.path.abspath(path),
        "qmt_python_dir": os.path.abspath(qmt_python_dir) if qmt_python_dir else None,
        "account_id": account_id,
        "account_config": os.path.abspath(config_path or DEFAULT_CONFIG),
        "spec": spec.canonical(),
        "strategy": spec.strategy,
        "params": spec.params,
        "assets": list(assets),
        "asset_first_dates": asset_first_dates or {},
        "universe_changes": universe_changes or [],
        "rebalance_dates": rebalance_dates or [],
        "nav_path": os.path.abspath(nav_path) if nav_path else None,
        "paper": paper,
        "source_sha256": sha,
        "note": "只生成文件；QMT 导入/启动/下单仍由人完成",
    }
    audit_path = os.path.join(out_dir, filename + ".json")
    with open(audit_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    copied = None
    if qmt_python_dir:
        os.makedirs(qmt_python_dir, exist_ok=True)
        copied = os.path.join(qmt_python_dir, filename)
        if os.path.exists(copied) and not force:
            raise QmtDeployError(f"QMT 目录已有同名文件，拒绝覆盖：{copied}")
        with open(copied, "w", encoding="gbk", errors="replace", newline="\n") as fh:
            fh.write(source)
    return {"source": path, "audit": audit_path, "qmt_copy": copied, "sha256": sha}
