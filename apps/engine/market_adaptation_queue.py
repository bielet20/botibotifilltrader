"""
Cola de revisión mercado ↔ perfiles guardados. Enlazada al orquestador y al laboratorio API.
Solo propone acciones revisables; mainnet nunca se activa desde aquí.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.engine.market_adaptation import analyze_symbol
from apps.shared.models import MarketAdaptationProfileDB, MarketAdaptationProposalDB
from apps.shared.notifications import notify_event


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def force_paper_bot_template(template: dict[str, Any]) -> dict[str, Any]:
    t = dict(template or {})
    t["executor"] = "paper"
    for k in (
        "hyperliquid_testnet",
        "paper_validation_passed",
        "candidate_for_production",
        "production_ready",
        "analysis_approved",
    ):
        t.pop(k, None)
    t.setdefault("managed_by", "market_adaptation_lab")
    return t


def _pending_exists(db: Session, fingerprint: str, symbol: str) -> bool:
    row = (
        db.query(MarketAdaptationProposalDB)
        .filter(
            MarketAdaptationProposalDB.fingerprint == fingerprint,
            MarketAdaptationProposalDB.symbol == symbol,
            MarketAdaptationProposalDB.status == "pending",
        )
        .first()
    )
    return row is not None


def create_proposal_if_eligible(
    db: Session,
    *,
    fingerprint: str,
    symbol: str,
    profile_id: str | None,
    bot_config_template: dict[str, Any],
    market_snapshot: dict[str, Any],
    source: str,
    trigger_ref: str | None = None,
    force_notify: bool = False,
) -> tuple[str | None, bool]:
    """
    Crea propuesta pending si no hay otra pendiente con mismo fingerprint+symbol.
    Devuelve (proposal_id, created).
    """
    if not fingerprint or not symbol:
        return None, False
    if _pending_exists(db, fingerprint, symbol):
        return None, False

    row = MarketAdaptationProposalDB(
        id=str(uuid.uuid4()),
        fingerprint=fingerprint,
        symbol=symbol,
        profile_id=profile_id,
        status="pending",
        source=str(source or "api")[:32],
        market_snapshot=dict(market_snapshot or {}),
        bot_config_template=force_paper_bot_template(bot_config_template),
        trigger_ref=(trigger_ref or "")[:120] or None,
    )
    db.add(row)
    db.flush()

    if force_notify or _env_bool("MARKET_ADAPTATION_NOTIFY_TELEGRAM", False):
        notify_event(
            "Adaptación mercado: revisión pendiente",
            {
                "proposal_id": row.id,
                "symbol": symbol,
                "fingerprint": fingerprint[:16],
                "source": source,
                "strategy": (bot_config_template or {}).get("strategy"),
            },
        )
    return row.id, True


async def orchestrator_tick(db: Session, symbols: list[str], *, trigger: str) -> dict[str, Any]:
    """
    Por cada símbolo: si el análisis actual coincide con un perfil guardado, encola propuesta (dedup).
    No crea bots ni toca mainnet.
    """
    if not _env_bool("MARKET_ADAPTATION_QUEUE_FROM_ORCHESTRATOR", True):
        return {"skipped": True, "reason": "MARKET_ADAPTATION_QUEUE_FROM_ORCHESTRATOR=false"}

    created: list[str] = []
    checked = 0
    for sym in symbols:
        s = str(sym or "").strip()
        if not s:
            continue
        checked += 1
        out = await analyze_symbol(s, limit=180)
        data_sym = str(out.get("data_symbol") or s).strip()
        fp = str(out.get("fingerprint") or "")
        prof = (
            db.query(MarketAdaptationProfileDB)
            .filter(
                MarketAdaptationProfileDB.symbol == data_sym,
                MarketAdaptationProfileDB.fingerprint == fp,
            )
            .first()
        )
        if not prof:
            continue
        snap = {
            "regime": out.get("regime"),
            "analysis": out.get("analysis"),
            "explanation_es": out.get("explanation_es"),
            "recommended_strategy": out.get("recommended_strategy"),
            "requested_symbol": out.get("requested_symbol"),
            "data_symbol": data_sym,
        }
        tmpl = dict(out.get("bot_config_template") or prof.bot_config_template or {})
        pid, did = create_proposal_if_eligible(
            db,
            fingerprint=fp,
            symbol=data_sym,
            profile_id=prof.id,
            bot_config_template=tmpl,
            market_snapshot=snap,
            source="orchestrator",
            trigger_ref=trigger,
            force_notify=False,
        )
        if did and pid:
            created.append(pid)

    return {
        "skipped": False,
        "symbols_checked": checked,
        "proposals_created": created,
        "proposals_created_count": len(created),
    }


def enqueue_from_api_analyze(
    db: Session,
    *,
    out: dict[str, Any],
    had_existing_profile_before_save: bool,
    persist_done: bool,
    trigger_ref: str | None = None,
) -> dict[str, Any]:
    """
    Tras POST /analyze: encolar solo si el mercado coincide con un perfil ya existente
    (reproducción de condiciones), no en la primera creación del perfil.
    """
    should = False
    if out.get("matching_saved_profile"):
        should = True
    if persist_done and had_existing_profile_before_save:
        should = True
    if not should:
        return {"enqueued": False, "reason": "no_reuse_context"}

    sym = str(out.get("data_symbol") or out.get("requested_symbol") or "").strip()
    fp = str(out.get("fingerprint") or "")
    match = out.get("matching_saved_profile") or out.get("persisted_profile")
    profile_id = (match or {}).get("id") if isinstance(match, dict) else None
    tmpl = dict(out.get("bot_config_template") or {})
    snap = {
        "regime": out.get("regime"),
        "analysis": out.get("analysis"),
        "explanation_es": out.get("explanation_es"),
        "recommended_strategy": out.get("recommended_strategy"),
        "trigger": trigger_ref or "api_analyze",
    }
    pid, did = create_proposal_if_eligible(
        db,
        fingerprint=fp,
        symbol=sym,
        profile_id=profile_id,
        bot_config_template=tmpl,
        market_snapshot=snap,
        source="api",
        trigger_ref=trigger_ref or "api_analyze",
        force_notify=False,
    )
    return {"enqueued": did, "proposal_id": pid}
