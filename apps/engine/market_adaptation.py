"""
Análisis de régimen por símbolo y generación de plantillas de bot alineadas con la tendencia/volatilidad.
Usado por la API /api/market-adaptation/* y la zona "Laboratorio de adaptación" en el dashboard.
"""
from __future__ import annotations

import hashlib
import json
from statistics import mean, pstdev
from typing import Any

from apps.engine.market_data import MarketDataEngine


def _normalize_ohlcv_row(c: dict) -> dict:
    ts = c.get("time")
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone

        t_iso = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
    else:
        t_iso = str(ts or "")
    return {
        "time": t_iso,
        "open": float(c.get("open") or 0.0),
        "high": float(c.get("high") or 0.0),
        "low": float(c.get("low") or 0.0),
        "close": float(c.get("close") or 0.0),
        "volume": float(c.get("volume") or 0.0),
    }


def compute_candle_analysis(candles: list[dict]) -> dict[str, Any]:
    if not candles:
        return {
            "trend_pct": 0.0,
            "volatility_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "range_pct": 0.0,
            "avg_volume": 0.0,
            "last_close": 0.0,
        }

    rows: list[dict] = []
    for c in candles:
        if isinstance(c.get("time"), (int, float)):
            rows.append(_normalize_ohlcv_row(c))
        else:
            rows.append(
                {
                    "time": c.get("time"),
                    "open": float(c.get("open") or 0.0),
                    "high": float(c.get("high") or 0.0),
                    "low": float(c.get("low") or 0.0),
                    "close": float(c.get("close") or 0.0),
                    "volume": float(c.get("volume") or 0.0),
                }
            )
    closes = [float(c.get("close") or 0.0) for c in rows if float(c.get("close") or 0.0) > 0]
    highs = [float(c.get("high") or 0.0) for c in rows if float(c.get("high") or 0.0) > 0]
    lows = [float(c.get("low") or 0.0) for c in rows if float(c.get("low") or 0.0) > 0]
    volumes = [float(c.get("volume") or 0.0) for c in rows]

    returns_pct: list[float] = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        cur = closes[idx]
        if prev > 0:
            returns_pct.append(((cur - prev) / prev) * 100)

    volatility_pct = 0.0
    if len(returns_pct) > 1:
        volatility_pct = float(pstdev(returns_pct))
    elif returns_pct:
        volatility_pct = float(mean(returns_pct))

    trend_pct = 0.0
    if len(closes) >= 2 and closes[0] > 0:
        trend_pct = ((closes[-1] - closes[0]) / closes[0]) * 100

    max_drawdown_pct = 0.0
    if closes:
        peak = closes[0]
        max_dd = 0.0
        for price in closes:
            if price > peak:
                peak = price
            if peak > 0:
                dd = ((price - peak) / peak) * 100
                if dd < max_dd:
                    max_dd = dd
        max_drawdown_pct = abs(max_dd)

    range_pct = 0.0
    if highs and lows:
        min_low = min(lows)
        max_high = max(highs)
        if min_low > 0:
            range_pct = ((max_high - min_low) / min_low) * 100

    avg_volume = (sum(volumes) / len(volumes)) if volumes else 0.0
    last_close = closes[-1] if closes else 0.0

    return {
        "trend_pct": round(trend_pct, 3),
        "volatility_pct": round(volatility_pct, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "range_pct": round(range_pct, 3),
        "avg_volume": round(avg_volume, 4),
        "last_close": round(last_close, 6),
    }


def regime_from_analysis(analysis: dict[str, Any]) -> str:
    trend_pct = float((analysis or {}).get("trend_pct") or 0.0)
    volatility_pct = float((analysis or {}).get("volatility_pct") or 0.0)
    if trend_pct >= 2.5:
        return "bullish"
    if trend_pct <= -2.5:
        return "bearish"
    if abs(trend_pct) < 1.2 and volatility_pct >= 1.8:
        return "sideways_volatile"
    return "sideways"


def discrete_trend_bucket(trend_pct: float) -> str:
    if trend_pct >= 3.0:
        return "strong_up"
    if trend_pct >= 1.0:
        return "mild_up"
    if trend_pct <= -3.0:
        return "strong_down"
    if trend_pct <= -1.0:
        return "mild_down"
    return "flat"


def discrete_vol_bucket(volatility_pct: float) -> str:
    if volatility_pct >= 2.0:
        return "high"
    if volatility_pct >= 1.0:
        return "mid"
    return "low"


def fingerprint_for(symbol: str, regime: str, trend_b: str, vol_b: str) -> str:
    key = json.dumps(
        {"symbol": symbol.strip().upper(), "regime": regime, "trend_b": trend_b, "vol_b": vol_b},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _grid_template(symbol: str, analysis: dict[str, Any], *, vol_mult: float = 1.0) -> dict[str, Any]:
    last = float(analysis.get("last_close") or 0.0)
    if last <= 0:
        last = 1.0
    vol = float(analysis.get("volatility_pct") or 1.0)
    # Banda mínima para cubrir fees típicos; escala con volatilidad observada.
    band_pct = max(0.04, min(0.16, (0.025 + (vol / 100.0) * 2.5) * vol_mult))
    upper = round(last * (1.0 + band_pct), 2)
    lower = round(last * (1.0 - band_pct), 2)
    grids = 22 if vol >= 1.5 else 30
    return {
        "strategy": "grid_trading",
        "symbol": symbol,
        "upper_limit": upper,
        "lower_limit": lower,
        "num_grids": grids,
        "grid_seed_entry": False,
        "executor": "paper",
        "capital_allocation": 400.0,
        "managed_by": "market_adaptation_lab",
    }


def _ema_trend_template(symbol: str, *, fast: int, slow: int, amount: float) -> dict[str, Any]:
    return {
        "strategy": "ema_cross",
        "symbol": symbol,
        "fast_ema": fast,
        "slow_ema": slow,
        "trade_amount": amount,
        "ema_min_spread_pct": 0.00035,
        "ema_min_slope_pct": 0.00012,
        "executor": "paper",
        "capital_allocation": 400.0,
        "managed_by": "market_adaptation_lab",
    }


def _adaptive_template(
    symbol: str, *, short_w: int, long_w: int, base_amt: float
) -> dict[str, Any]:
    return {
        "strategy": "adaptive_learning",
        "symbol": symbol,
        "adaptive_short_window": short_w,
        "adaptive_long_window": long_w,
        "adaptive_base_amount": base_amt,
        "executor": "paper",
        "capital_allocation": 400.0,
        "managed_by": "market_adaptation_lab",
    }


def build_recommendation(
    symbol: str, regime: str, analysis: dict[str, Any]
) -> tuple[str, dict[str, Any], str]:
    """
    Devuelve (estrategia, plantilla_config_sin_id, explicación breve en español).
    """
    sym = symbol.strip() or "BTC/USDT"
    if regime == "bullish":
        return (
            "ema_cross",
            _ema_trend_template(sym, fast=10, slow=26, amount=0.0025),
            "Tendencia alcista: plantilla EMA más lenta para seguir el impulso (paper por defecto).",
        )
    if regime == "bearish":
        return (
            "adaptive_learning",
            _adaptive_template(sym, short_w=10, long_w=36, base_amt=0.008),
            "Tendencia bajista: plantilla adaptativa más reactiva (sin apalancamiento corto explícito).",
        )
    if regime == "sideways_volatile":
        return (
            "adaptive_learning",
            _adaptive_template(sym, short_w=8, long_w=28, base_amt=0.006),
            "Lateral volátil: evita rejilla densa; adaptativo con ventanas cortas.",
        )
    if regime == "sideways":
        return (
            "grid_trading",
            _grid_template(sym, analysis, vol_mult=1.0),
            "Lateral: rejilla centrada en precio actual con paso amplio para amortizar fees.",
        )
    return (
        "adaptive_learning",
        _adaptive_template(sym, short_w=12, long_w=48, base_amt=0.01),
        "Régimen mixto: adaptativo equilibrado hasta que el mercado defina rango o tendencia.",
    )


def _fallback_binance_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if raw.endswith(":USDC") and "/USDC" in raw:
        return f"{raw.split('/')[0]}/USDT"
    return str(symbol or "").strip()


async def analyze_symbol(symbol: str, *, limit: int = 200) -> dict[str, Any]:
    """
    Descarga OHLCV (Binance por defecto en MarketDataEngine), calcula régimen y plantilla sugerida.
    """
    sym = (symbol or "BTC/USDT").strip()
    mde = MarketDataEngine()
    candles: list[dict] = []
    data_symbol = sym
    try:
        raw = await mde.fetch_ohlcv(sym, timeframe="1h", limit=max(48, min(int(limit or 200), 1000)))
        candles = raw or []
        if not candles:
            fb = _fallback_binance_symbol(sym)
            if fb and fb != sym:
                raw = await mde.fetch_ohlcv(fb, timeframe="1h", limit=max(48, min(int(limit or 200), 1000)))
                candles = raw or []
                data_symbol = fb
    finally:
        try:
            await mde.close()
        except Exception:
            pass

    analysis = compute_candle_analysis(candles[-240:] if candles else [])
    regime = regime_from_analysis(analysis) if candles else "mixed"
    trend_b = discrete_trend_bucket(float(analysis.get("trend_pct") or 0.0))
    vol_b = discrete_vol_bucket(float(analysis.get("volatility_pct") or 0.0))
    fp = fingerprint_for(data_symbol, regime, trend_b, vol_b)
    strat, template, explanation_es = build_recommendation(data_symbol, regime, analysis)

    return {
        "requested_symbol": sym,
        "data_symbol": data_symbol,
        "candles_used": len(candles),
        "analysis": analysis,
        "regime": regime,
        "trend_bucket": trend_b,
        "vol_bucket": vol_b,
        "fingerprint": fp,
        "recommended_strategy": strat,
        "explanation_es": explanation_es,
        "bot_config_template": template,
    }
