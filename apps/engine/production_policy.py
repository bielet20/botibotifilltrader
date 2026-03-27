"""
Política unificada para producción: ventana de métricas, puntuación de candidatos
y validación mínima de entrada. Evita duplicar reglas entre API y orquestador.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Tuple


def resolve_monitoring_window_params() -> Tuple[int, int]:
    """
    Prioridad: AUTOPILOT_* → ORCHESTRATOR_AUTO_START_* → PRODUCTION_AUTO_PROMOTE_* → defaults.
    """
    raw_lb = (
        os.getenv("AUTOPILOT_MONITORING_LOOKBACK_HOURS")
        or os.getenv("ORCHESTRATOR_AUTO_START_LOOKBACK_HOURS")
        or os.getenv("PRODUCTION_AUTO_PROMOTE_LOOKBACK_HOURS")
        or "24"
    )
    raw_mt = (
        os.getenv("AUTOPILOT_MONITORING_MIN_SCORED_TRADES")
        or os.getenv("ORCHESTRATOR_AUTO_START_MIN_SCORED_TRADES")
        or os.getenv("PRODUCTION_AUTO_PROMOTE_MIN_SCORED_TRADES")
        or "6"
    )
    try:
        lookback = max(1, int(raw_lb))
    except ValueError:
        lookback = 24
    try:
        min_scored = max(1, int(raw_mt))
    except ValueError:
        min_scored = 6
    return lookback, min_scored


def resolve_daily_blockers_params() -> Tuple[int, int]:
    """
    Ventana para informes de bloqueos diarios.
    Prioridad: AUTOPILOT_BLOCKERS_* → PRODUCTION_BLOCKERS_DAILY_* → defaults.
    """
    raw_lb = (
        os.getenv("AUTOPILOT_BLOCKERS_LOOKBACK_HOURS")
        or os.getenv("PRODUCTION_BLOCKERS_DAILY_LOOKBACK_HOURS")
        or "24"
    )
    raw_mt = (
        os.getenv("AUTOPILOT_BLOCKERS_MIN_SCORED_TRADES")
        or os.getenv("PRODUCTION_BLOCKERS_DAILY_MIN_SCORED_TRADES")
        or "6"
    )
    try:
        lookback = max(1, int(raw_lb))
    except ValueError:
        lookback = 24
    try:
        min_scored = max(1, int(raw_mt))
    except ValueError:
        min_scored = 6
    return lookback, min_scored


def hyperliquid_testnet_resolved(cfg: Mapping[str, Any] | None) -> bool:
    """
    True si Hyperliquid opera en testnet: valor explícito en config o
    HYPERLIQUID_USE_TESTNET cuando la clave no está definida (misma lógica que la API).
    """
    conf = dict(cfg or {})
    if "hyperliquid_testnet" in conf and conf.get("hyperliquid_testnet") is not None:
        return bool(conf.get("hyperliquid_testnet"))
    return os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"


def config_promotion_flag_ok(cfg: Mapping[str, Any] | None) -> bool:
    """Flags de config (sin gate estadístico). Alineado con _analysis_gate_ok en main."""
    c = dict(cfg or {})
    return bool(
        c.get("analysis_approved")
        or c.get("candidate_for_production")
        or c.get("production_ready")
    )


def is_verified_for_production(cfg: Mapping[str, Any] | None) -> bool:
    c = dict(cfg or {})
    return bool(
        c.get("analysis_approved")
        or c.get("candidate_for_production")
        or c.get("production_ready")
        or c.get("autoadapt_mainnet_candidate")
    )


def is_live_mainnet_config(cfg: Mapping[str, Any] | None) -> bool:
    c = dict(cfg or {})
    executor = str(c.get("executor") or "paper").strip().lower()
    if executor != "hyperliquid":
        return False
    return not hyperliquid_testnet_resolved(c)


def entry_params_ok_for_live(cfg: Mapping[str, Any] | None) -> bool:
    c = dict(cfg or {})
    sym = str(c.get("symbol") or "").strip()
    if not sym:
        return False
    alloc = float(c.get("capital_allocation") or c.get("allocation") or 0.0)
    return alloc > 0.0


def score_rotation_managed_bot(metrics: Mapping[str, Any], cfg: Mapping[str, Any] | None) -> float:
    """
    Puntuación para rotación por capacidad (bots gestionados en ejecución).
    Misma base que autostart; bonifica live verificado y penaliza paper.
    """
    m = dict(metrics or {})
    c = dict(cfg or {})
    win_rate = float(m.get("win_rate") or 0.0)
    net_pnl = float(m.get("net_pnl") or 0.0)
    cons = float(m.get("consecutive_losses") or 0.0)
    score = (win_rate * 0.7) + (net_pnl * 0.1) - (cons * 12.0)
    if is_live_mainnet_config(c):
        score += 1000.0
    if is_verified_for_production(c):
        score += 250.0
    if str(c.get("executor") or "paper").strip().lower() == "paper":
        score -= 150.0
    return score


def score_autostart_from_monitoring_row(
    cfg: Mapping[str, Any] | None,
    monitoring_row: Mapping[str, Any],
    orchestrator_symbols: List[str],
    market_context_by_symbol: Mapping[str, Mapping[str, Any]],
) -> float:
    """Ordenar candidatos parados que ya pasaron gate + filtros de executor."""
    c = dict(cfg or {})
    item = dict(monitoring_row or {})
    metrics = dict(item.get("metrics") or {})
    win_rate = float(metrics.get("win_rate") or 0.0)
    net_pnl = float(metrics.get("net_pnl") or 0.0)
    cons = int(metrics.get("consecutive_losses") or 0)
    score = (win_rate * 0.7) + (net_pnl * 0.1) - (cons * 12.0)
    sym = str(c.get("symbol") or "").strip().upper()
    if sym in orchestrator_symbols:
        score += 80.0
    live_ctx = dict(market_context_by_symbol.get(sym) or {})
    regime = str(live_ctx.get("regime") or live_ctx.get("trend") or "").strip().lower()
    if regime in {"bull", "bullish", "trending_up", "uptrend"}:
        score += 12.0
    if is_verified_for_production(c):
        score += 250.0
    conf = float(c.get("autoadapt_confidence") or 0.0)
    score += conf * 0.05
    return score


def promotion_sort_key(item: Mapping[str, Any]) -> Tuple:
    """Orden estable para listas de monitoring (reutilizable en API)."""
    readiness = dict(item.get("readiness") or {})
    gate_ok = bool(readiness.get("gate_ok"))
    metrics = dict(item.get("metrics") or {})
    return (
        gate_ok,
        bool(item.get("candidate_for_production")),
        float(metrics.get("net_pnl") or 0.0),
        float(metrics.get("win_rate") or 0.0),
    )
