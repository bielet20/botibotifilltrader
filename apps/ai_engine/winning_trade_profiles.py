"""
Perfiles derivados de trades históricos con PnL > 0: estrategia, lado, executor y
alineación con régimen (Copiloto / advisor) para sugerir clones o parámetros similares.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func

from apps.shared.models import AutopilotDecisionLogDB, BotDB, TradeDB


def _norm_symbol(sym: str) -> str:
    s = str(sym or "").strip().upper()
    if ":" in s:
        s = s.split(":", 1)[0]
    return s


def _config_snippet(cfg: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "strategy",
        "fast_ema",
        "slow_ema",
        "trade_amount",
        "amount",
        "adaptive_short_window",
        "adaptive_long_window",
        "adaptive_base_amount",
        "executor",
        "hyperliquid_testnet",
        "ema_min_spread_pct",
        "ema_min_slope_pct",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        if k in cfg and cfg[k] is not None:
            out[k] = cfg[k]
    return out


def _regime_similar(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """0..1 score de similitud entre dos contextos de mercado."""
    if not a or not b:
        return 0.0
    r1 = str(a.get("regime") or "").strip().lower()
    r2 = str(b.get("regime") or "").strip().lower()
    score = 0.0
    if r1 and r2 and r1 == r2:
        score += 0.45
    try:
        t1 = float(a.get("trend_pct") or 0.0)
        t2 = float(b.get("trend_pct") or 0.0)
        if abs(t1 - t2) <= 0.6:
            score += 0.35
        elif abs(t1 - t2) <= 1.5:
            score += 0.18
    except Exception:
        pass
    try:
        v1 = float(a.get("volatility_pct") or 0.0)
        v2 = float(b.get("volatility_pct") or 0.0)
        if max(v1, v2, 1e-9) > 0 and abs(v1 - v2) / max(v1, v2, 1e-9) <= 0.35:
            score += 0.2
    except Exception:
        pass
    return min(1.0, score)


def _sample_autopilot_contexts_for_bot(
    db,
    bot_id: str,
    since: Optional[datetime] = None,
    limit: int = 80,
) -> List[Dict[str, Any]]:
    q = db.query(AutopilotDecisionLogDB).filter(AutopilotDecisionLogDB.bot_id == bot_id)
    if since:
        q = q.filter(AutopilotDecisionLogDB.created_at >= since)
    rows = q.order_by(AutopilotDecisionLogDB.created_at.desc()).limit(limit).all()
    out = []
    for row in rows:
        ctx = dict(row.market_context or {})
        if ctx:
            out.append(ctx)
    return out


def aggregate_winning_trades_by_bot(
    db,
    *,
    symbol_filter: Optional[str] = None,
    min_trades: int = 1,
) -> List[Dict[str, Any]]:
    """
    Agrupa trades con pnl > 0 por bot, con métricas y snippet de config actual del bot.
    """
    q = (
        db.query(
            TradeDB.bot_id,
            func.count(TradeDB.id).label("win_count"),
            func.sum(TradeDB.pnl).label("sum_pnl"),
            func.avg(TradeDB.pnl).label("avg_pnl"),
        )
        .filter(TradeDB.pnl > 0)
        .group_by(TradeDB.bot_id)
    )
    if symbol_filter:
        nf = _norm_symbol(symbol_filter)
        q = q.filter(func.upper(TradeDB.symbol).like(f"%{nf.replace('/', '%')}%"))

    rows = q.order_by(func.sum(TradeDB.pnl).desc()).all()
    result: List[Dict[str, Any]] = []
    for bot_id, win_count, sum_pnl, avg_pnl in rows:
        if int(win_count or 0) < min_trades:
            continue
        bot = db.query(BotDB).filter(BotDB.id == bot_id).first()
        cfg = dict(bot.config or {}) if bot else {}
        sides = [
            t.side
            for t in db.query(TradeDB).filter(TradeDB.bot_id == bot_id, TradeDB.pnl > 0).all()
        ]
        side_hist = dict(Counter(str(s).lower() for s in sides))
        dominant_side = max(side_hist, key=side_hist.get) if side_hist else ""

        result.append(
            {
                "bot_id": bot_id,
                "strategy": (bot.strategy if bot else None) or cfg.get("strategy"),
                "win_count": int(win_count or 0),
                "sum_pnl": round(float(sum_pnl or 0.0), 6),
                "avg_pnl": round(float(avg_pnl or 0.0), 6),
                "winning_order_sides": side_hist,
                "dominant_order_side": dominant_side,
                "position_exit_hint": (
                    "cierra_longs_con_ventas_rentables"
                    if dominant_side == "sell"
                    else "compras_rentables_o_cierra_shorts"
                    if dominant_side == "buy"
                    else "mixto"
                ),
                "executor": str(cfg.get("executor") or "paper").lower(),
                "hyperliquid_testnet": bool(cfg.get("hyperliquid_testnet", True)),
                "config_snapshot": _config_snippet(cfg),
            }
        )
    return result


def build_advisor_hints(
    db,
    symbol: str,
    market_context: Dict[str, Any],
    *,
    lookback_days: int = 45,
) -> Dict[str, Any]:
    """
    Resume setups ganadores y su alineación con el régimen actual para el asesor / UI.
    """
    sym = symbol.strip() or "BTC/USDT"
    winners = aggregate_winning_trades_by_bot(db, symbol_filter=sym, min_trades=1)
    # También incluir agregados globales si el símbolo filtra demasiado poco
    if len(winners) < 2:
        winners = aggregate_winning_trades_by_bot(db, symbol_filter=None, min_trades=1)[:12]

    since = datetime.utcnow() - timedelta(days=lookback_days)
    regime = market_context or {}
    enriched: List[Dict[str, Any]] = []
    best_match: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)

    for w in winners:
        ctxs = _sample_autopilot_contexts_for_bot(db, w["bot_id"], since=since, limit=60)
        sims = [_regime_similar(regime, c) for c in ctxs]
        avg_sim = sum(sims) / len(sims) if sims else 0.0
        max_sim = max(sims) if sims else 0.0
        row = dict(w)
        row["regime_similarity_vs_current"] = round(avg_sim, 4)
        row["regime_similarity_max"] = round(max_sim, 4)
        row["copilot_context_samples"] = len(ctxs)
        enriched.append(row)
        if max_sim > best_match[0]:
            best_match = (max_sim, row)

    live_winners = [x for x in enriched if x.get("executor") == "hyperliquid" and not x.get("hyperliquid_testnet")]
    paper_winners = [x for x in enriched if x.get("executor") == "paper"]

    suggested_clone: Optional[Dict[str, Any]] = None
    if best_match[1] and best_match[0] >= 0.45:
        suggested_clone = {
            "source_bot_id": best_match[1].get("bot_id"),
            "reason": "historical_regime_alignment",
            "similarity": round(best_match[0], 4),
            "config_snapshot": deepcopy(best_match[1].get("config_snapshot") or {}),
        }

    return {
        "symbol": sym,
        "current_market_context": dict(regime),
        "winning_setups_ranked": enriched[:15],
        "hyperliquid_mainnet_winners": live_winners[:5],
        "paper_lab_winners": paper_winners[:5],
        "best_regime_match": suggested_clone,
        "notes_es": (
            "Los trades con PnL>0 en paper suelen ser cierres (más 'sell' si el bot era long). "
            "En mainnet prioriza clonar parámetros de bots HL con beneficios reales y régimen parecido."
        ),
    }


def merge_winning_config_hints(
    base_config: Dict[str, Any],
    hints: Dict[str, Any],
    *,
    min_similarity: float = 0.42,
) -> Dict[str, Any]:
    """
    Copia conservadora de fast/slow EMA y tamaños desde un setup ganador alineado con el régimen.
    No sustituye executor ni símbolo.
    """
    out = deepcopy(base_config or {})
    best = hints.get("best_regime_match") if isinstance(hints, dict) else None
    if not best or float(best.get("similarity") or 0.0) < min_similarity:
        return out
    snap = dict(best.get("config_snapshot") or {})
    strat = str(out.get("strategy") or "").lower()
    src_strat = str(snap.get("strategy") or "").lower()
    if strat == "ema_cross" and src_strat == "ema_cross":
        if "fast_ema" in snap:
            out["fast_ema"] = int(snap["fast_ema"])
        if "slow_ema" in snap:
            out["slow_ema"] = int(snap["slow_ema"])
        for k in ("ema_min_spread_pct", "ema_min_slope_pct"):
            if k in snap:
                out[k] = snap[k]
    elif strat == "adaptive_learning" and src_strat == "adaptive_learning":
        for k in ("adaptive_short_window", "adaptive_long_window", "adaptive_base_amount"):
            if k in snap:
                out[k] = snap[k]
    out["winning_hint_source_bot"] = best.get("source_bot_id")
    out["winning_hint_similarity"] = best.get("similarity")
    return out
