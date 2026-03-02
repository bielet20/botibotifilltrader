from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

try:
    from statsmodels.tsa.stattools import adfuller
except Exception:
    adfuller = None

from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _series_returns(values: List[float]) -> List[float]:
    output: List[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        cur = values[i]
        if prev > 0:
            output.append((cur - prev) / prev)
    return output


def _correlation(a: List[float], b: List[float]) -> float:
    n = min(len(a), len(b))
    if n < 5:
        return 0.0

    a = a[-n:]
    b = b[-n:]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((x - mean_b) ** 2 for x in b)
    if var_a <= 0 or var_b <= 0:
        return 0.0

    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    return cov / math.sqrt(var_a * var_b)


@dataclass
class PairDecision:
    action: str
    side_a: TradeSide
    side_b: TradeSide
    reason: str
    zscore: float
    correlation: float
    spread: float
    mean_spread: float
    std_spread: float
    cadf_pvalue: Optional[float] = None
    cadf_stat: Optional[float] = None
    cadf_passed: Optional[bool] = None


def _cadf_cointegration_test(series_a: List[float], series_b: List[float]) -> Dict[str, Optional[float]]:
    if adfuller is None:
        return {"ok": False, "pvalue": None, "stat": None}

    n = min(len(series_a), len(series_b))
    if n < 40:
        return {"ok": False, "pvalue": None, "stat": None}

    a = np.asarray(series_a[-n:], dtype=float)
    b = np.asarray(series_b[-n:], dtype=float)

    if np.std(a) <= 1e-12 or np.std(b) <= 1e-12:
        return {"ok": False, "pvalue": None, "stat": None}

    try:
        slope, intercept = np.polyfit(b, a, 1)
        residuals = a - (slope * b + intercept)
        if np.std(residuals) <= 1e-12:
            return {"ok": False, "pvalue": None, "stat": None}
        result = adfuller(residuals, regression="c", autolag="AIC")
        stat = float(result[0])
        pvalue = float(result[1])
        return {"ok": True, "pvalue": pvalue, "stat": stat}
    except Exception:
        return {"ok": False, "pvalue": None, "stat": None}


class PairedBalancedStrategy(BaseStrategy):
    def __init__(self, lookback: int = 120):
        self.lookback = max(50, int(lookback))

    async def analyze(self, market_data: dict) -> TradeSignal:
        return TradeSignal(
            symbol=market_data.get("symbol", "BTC/USDT"),
            side=TradeSide.HOLD,
            amount=0.0,
            price=float(market_data.get("last_price") or 0.0),
            strategy_id="Paired_Balanced_v1",
            meta={"reason": "paired_strategy_uses_custom_manager_loop"},
        )

    def evaluate(self, market_data: Dict) -> PairDecision:
        closes_a = [float(c.get("close") or 0.0) for c in (market_data.get("history_a") or [])]
        closes_b = [float(c.get("close") or 0.0) for c in (market_data.get("history_b") or [])]
        closes_a = [x for x in closes_a if x > 0]
        closes_b = [x for x in closes_b if x > 0]

        lookback = min(self.lookback, len(closes_a), len(closes_b))
        if lookback < 40:
            return PairDecision(
                action="hold",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="insufficient_history",
                zscore=0.0,
                correlation=0.0,
                spread=0.0,
                mean_spread=0.0,
                std_spread=0.0,
                cadf_pvalue=None,
                cadf_stat=None,
                cadf_passed=None,
            )

        aa = closes_a[-lookback:]
        bb = closes_b[-lookback:]
        spreads = [math.log(aa[i] / bb[i]) for i in range(lookback) if aa[i] > 0 and bb[i] > 0]
        if len(spreads) < 30:
            return PairDecision(
                action="hold",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="insufficient_spread",
                zscore=0.0,
                correlation=0.0,
                spread=0.0,
                mean_spread=0.0,
                std_spread=0.0,
                cadf_pvalue=None,
                cadf_stat=None,
                cadf_passed=None,
            )

        mean_spread = sum(spreads) / len(spreads)
        variance = sum((s - mean_spread) ** 2 for s in spreads) / len(spreads)
        std_spread = math.sqrt(max(variance, 1e-12))
        spread_now = spreads[-1]
        zscore = (spread_now - mean_spread) / std_spread

        corr = _correlation(_series_returns(aa), _series_returns(bb))

        entry_z = float(market_data.get("entry_z", 1.4) or 1.4)
        exit_z = float(market_data.get("exit_z", 0.25) or 0.25)
        min_corr = float(market_data.get("min_correlation", 0.35) or 0.35)
        enable_cadf = bool(market_data.get("enable_cadf", True))
        cadf_alpha = float(market_data.get("cadf_alpha", 0.05) or 0.05)

        cadf_res = _cadf_cointegration_test(aa, bb)
        cadf_ok = bool(cadf_res.get("ok"))
        cadf_pvalue = cadf_res.get("pvalue")
        cadf_stat = cadf_res.get("stat")
        cadf_passed = (cadf_ok and cadf_pvalue is not None and cadf_pvalue <= cadf_alpha) if enable_cadf else None

        if enable_cadf and (not cadf_ok):
            return PairDecision(
                action="hold",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="cadf_unavailable",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=False,
            )

        if enable_cadf and not cadf_passed:
            return PairDecision(
                action="hold",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="cadf_not_cointegrated",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=False,
            )

        if corr < min_corr:
            return PairDecision(
                action="hold",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="low_correlation",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=cadf_passed,
            )

        if abs(zscore) <= exit_z:
            return PairDecision(
                action="close_pair",
                side_a=TradeSide.HOLD,
                side_b=TradeSide.HOLD,
                reason="mean_reversion_reached",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=cadf_passed,
            )

        if zscore >= entry_z:
            return PairDecision(
                action="open_pair",
                side_a=TradeSide.SELL,
                side_b=TradeSide.BUY,
                reason="spread_high_short_a_long_b",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=cadf_passed,
            )

        if zscore <= -entry_z:
            return PairDecision(
                action="open_pair",
                side_a=TradeSide.BUY,
                side_b=TradeSide.SELL,
                reason="spread_low_long_a_short_b",
                zscore=zscore,
                correlation=corr,
                spread=spread_now,
                mean_spread=mean_spread,
                std_spread=std_spread,
                cadf_pvalue=cadf_pvalue,
                cadf_stat=cadf_stat,
                cadf_passed=cadf_passed,
            )

        return PairDecision(
            action="hold",
            side_a=TradeSide.HOLD,
            side_b=TradeSide.HOLD,
            reason="between_bands",
            zscore=zscore,
            correlation=corr,
            spread=spread_now,
            mean_spread=mean_spread,
            std_spread=std_spread,
            cadf_pvalue=cadf_pvalue,
            cadf_stat=cadf_stat,
            cadf_passed=cadf_passed,
        )

    @staticmethod
    def allocation_factor(correlation: float, zscore: float) -> float:
        corr_boost = _clamp(correlation, 0.2, 1.0)
        signal_boost = _clamp(abs(zscore) / 2.5, 0.35, 1.0)
        return _clamp(corr_boost * signal_boost, 0.25, 1.0)
