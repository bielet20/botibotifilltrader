import argparse
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

import ccxt.async_support as ccxt
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.shared.hyperliquid_credentials import get_hyperliquid_wallet_and_key


BALANCED_TRAILING_LADDER = [(0.02, 0.0075), (0.05, 0.006), (0.10, 0.0045)]
CONSERVATIVE_TRAILING_LADDER = [(0.015, 0.01), (0.03, 0.008), (0.06, 0.0065)]
AGGRESSIVE_TRAILING_LADDER = [(0.025, 0.0065), (0.06, 0.005), (0.12, 0.0035)]


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _symbol_base(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return ""
    left = raw.split("/", 1)[0]
    return left.split(":", 1)[0]


def _infer_side_qty(pos: dict) -> tuple[str, float]:
    """Infer canonical side/qty from CCXT Hyperliquid position payload variants."""
    info = pos.get("info") or {}
    nested_pos = info.get("position") if isinstance(info.get("position"), dict) else {}
    raw_side = str(pos.get("side") or nested_pos.get("side") or info.get("side") or "").strip().lower()

    signed_size = None
    for candidate in (
        nested_pos.get("szi"),
        info.get("szi"),
        info.get("size"),
        pos.get("contracts"),
    ):
        try:
            if candidate is not None and str(candidate).strip() != "":
                signed_size = float(candidate)
                break
        except Exception:
            continue

    if signed_size is None:
        return "", 0.0

    qty = abs(float(signed_size))
    if qty <= 0:
        return "", 0.0

    if raw_side in {"long", "buy"}:
        return "long", qty
    if raw_side in {"short", "sell"}:
        return "short", qty
    return ("long", qty) if signed_size > 0 else ("short", qty)


def _extract_funding_pnl(pos: dict) -> float:
    """Best-effort extraction of funding PnL from heterogeneous Hyperliquid payloads."""
    info = pos.get("info") or {}
    nested_pos = info.get("position") if isinstance(info.get("position"), dict) else {}

    signed_candidates = [
        nested_pos.get("fundingPnl"),
        info.get("fundingPnl"),
        nested_pos.get("cumFunding"),
        info.get("cumFunding"),
        nested_pos.get("funding"),
        info.get("funding"),
        nested_pos.get("totalFunding"),
        info.get("totalFunding"),
    ]
    for candidate in signed_candidates:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except Exception:
            continue

    cost_candidates = [
        nested_pos.get("fundingFee"),
        info.get("fundingFee"),
        nested_pos.get("funding_fee"),
        info.get("funding_fee"),
    ]
    for candidate in cost_candidates:
        if candidate is None:
            continue
        try:
            return -abs(float(candidate))
        except Exception:
            continue

    return 0.0


def _load_active_production_targets() -> dict:
    """Load active production bot targets from API runtime state."""
    payload = {
        "symbols": set(),
        "bases": set(),
        "bot_ids": set(),
    }
    with urllib.request.urlopen("http://127.0.0.1:8000/api/bots?include_system=true", timeout=10) as response:
        bots = json.loads(response.read().decode())

    for bot in bots or []:
        status = str(bot.get("status") or "").strip().lower()
        cfg = dict(bot.get("config") or {})
        executor = str(cfg.get("executor") or "paper").strip().lower()
        prepared = bool(
            cfg.get("production_ready")
            or cfg.get("candidate_for_production")
            or cfg.get("analysis_approved")
        )
        is_mainnet = executor == "hyperliquid" and (not _to_bool(cfg.get("hyperliquid_testnet"), default=False))
        if status != "running" or not prepared or not is_mainnet:
            continue

        symbol = str(cfg.get("symbol") or "").strip()
        if symbol:
            payload["symbols"].add(symbol.lower())
            base = _symbol_base(symbol)
            if base:
                payload["bases"].add(base)

        bot_id = str(bot.get("id") or "").strip()
        if bot_id:
            payload["bot_ids"].add(bot_id)

    return payload


def _state_file_path() -> Path:
    raw = os.getenv("HYPERLIQUID_TP_STATE_FILE", "reports/profit_guard_state.json")
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_state() -> dict:
    path = _state_file_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    path = _state_file_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _position_key(symbol: str, side: str, qty: float, entry: float) -> str:
    return f"{symbol}|{side}|{round(qty, 8)}|{round(entry, 8)}"


def _gain_pct(side: str, entry: float, mark: float) -> float:
    if entry <= 0 or mark <= 0:
        return 0.0
    if side == "short":
        return (entry - mark) / entry
    return (mark - entry) / entry


def _retrace_pct(side: str, best_price: float, mark: float) -> float:
    if best_price <= 0 or mark <= 0:
        return 0.0
    if side == "short":
        return max(0.0, (mark - best_price) / best_price)
    return max(0.0, (best_price - mark) / best_price)


def _parse_trailing_ladder(raw: str) -> list[tuple[float, float]]:
    """Parse trailing ladder entries like: 0.02:0.0075,0.05:0.006,0.1:0.0045"""
    items: list[tuple[float, float]] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        left, right = token.split(":", 1)
        gain_trigger = _to_float(left, -1)
        retrace = _to_float(right, -1)
        if gain_trigger > 0 and retrace > 0:
            items.append((gain_trigger, retrace))
    items.sort(key=lambda x: x[0])
    return items


def _resolve_trailing_retrace_pct(
    peak_gain_pct: float,
    default_retrace_pct: float,
    trailing_ladder: list[tuple[float, float]],
) -> float:
    retrace_pct = default_retrace_pct
    for trigger_gain, trigger_retrace in trailing_ladder:
        if peak_gain_pct >= trigger_gain:
            retrace_pct = trigger_retrace
        else:
            break
    return retrace_pct


async def _estimate_volatility_pct(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    lookback: int,
) -> float:
    try:
        candles = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=max(lookback, 10))
        if not candles or len(candles) < 2:
            return 0.0
        abs_returns = []
        prev_close = _to_float(candles[0][4], 0.0)
        for candle in candles[1:]:
            close = _to_float(candle[4], 0.0)
            if prev_close > 0 and close > 0:
                abs_returns.append(abs(close - prev_close) / prev_close)
            prev_close = close
        if not abs_returns:
            return 0.0
        return sum(abs_returns) / len(abs_returns)
    except Exception:
        return 0.0


def _select_trailing_ladder(
    profile: str,
    manual_ladder: list[tuple[float, float]],
    symbol_volatility_pct: float,
    vol_low_threshold_pct: float,
    vol_high_threshold_pct: float,
) -> tuple[list[tuple[float, float]], str]:
    if profile == "manual":
        return manual_ladder, "manual"
    if profile == "conservative":
        return CONSERVATIVE_TRAILING_LADDER, "conservative"
    if profile == "aggressive":
        return AGGRESSIVE_TRAILING_LADDER, "aggressive"

    # Auto mode: high volatility protects gains earlier, low volatility lets trend run.
    if symbol_volatility_pct >= vol_high_threshold_pct:
        return CONSERVATIVE_TRAILING_LADDER, "auto_conservative"
    if symbol_volatility_pct <= vol_low_threshold_pct:
        return AGGRESSIVE_TRAILING_LADDER, "auto_aggressive"
    return BALANCED_TRAILING_LADDER, "auto_balanced"


def _compute_dynamic_exit_thresholds(
    *,
    symbol_volatility_pct: float,
    vol_low_threshold_pct: float,
    vol_high_threshold_pct: float,
    stop_loss_pct: float,
    hard_take_profit_pct: float,
    trailing_trigger_pct: float,
    trailing_retrace_pct: float,
    min_net_pnl: float,
) -> dict:
    """
    Derive per-position effective TP/SL/trailing thresholds from current volatility.
    Goal: preserve gains sooner in high-volatility environments and reduce loss tails.
    """
    vol = max(0.0, float(symbol_volatility_pct or 0.0))
    low = max(1e-9, float(vol_low_threshold_pct or 0.0))
    high = max(low, float(vol_high_threshold_pct or 0.0))

    # Normalize volatility to [0,1] range between low and high thresholds.
    if high > low:
        vol_norm = max(0.0, min((vol - low) / (high - low), 1.0))
    else:
        vol_norm = 0.0

    # High volatility: tighter SL and earlier TP capture.
    # Low volatility: allow trend a bit more room.
    stop_loss_factor = 1.10 - (0.50 * vol_norm)  # 1.10 -> 0.60
    take_profit_factor = 1.05 - (0.35 * vol_norm)  # 1.05 -> 0.70
    trailing_trigger_factor = 1.0 - (0.30 * vol_norm)  # 1.0 -> 0.70
    trailing_retrace_factor = 1.05 - (0.45 * vol_norm)  # 1.05 -> 0.60

    effective_stop_loss_pct = max(0.0025, float(stop_loss_pct or 0.0) * stop_loss_factor)
    effective_hard_take_profit_pct = max(0.0015, float(hard_take_profit_pct or 0.0) * take_profit_factor)
    effective_trailing_trigger_pct = max(0.0012, float(trailing_trigger_pct or 0.0) * trailing_trigger_factor)
    effective_trailing_retrace_pct = max(0.0008, float(trailing_retrace_pct or 0.0) * trailing_retrace_factor)

    # Breakeven lock arms once the position had enough positive excursion.
    breakeven_arm_gain_pct = max(
        effective_trailing_trigger_pct * 0.6,
        vol * 1.25,
        0.0025,
    )
    # Small net cushion to avoid round-trip from winner to loser.
    breakeven_min_net_pnl = max(0.0, float(min_net_pnl or 0.0) * 0.20)

    return {
        "effective_stop_loss_pct": effective_stop_loss_pct,
        "effective_hard_take_profit_pct": effective_hard_take_profit_pct,
        "effective_trailing_trigger_pct": effective_trailing_trigger_pct,
        "effective_trailing_retrace_pct": effective_trailing_retrace_pct,
        "breakeven_arm_gain_pct": breakeven_arm_gain_pct,
        "breakeven_min_net_pnl": breakeven_min_net_pnl,
        "volatility_normalized": vol_norm,
    }


async def run(
    execute: bool,
    min_net_pnl: float,
    min_net_profit_pct: float,
    hard_take_profit_pct: float,
    trailing_trigger_pct: float,
    trailing_retrace_pct: float,
    stop_loss_pct: float,
    max_net_loss_abs: float,
    exit_slippage_pct: float,
    only_production_positions: bool,
    trailing_ladder_raw: str,
    trailing_profile: str,
    volatility_timeframe: str,
    volatility_lookback: int,
    volatility_low_threshold_pct: float,
    volatility_high_threshold_pct: float,
) -> dict:
    load_dotenv(override=True)
    wallet_raw, key_raw = get_hyperliquid_wallet_and_key()
    wallet = str(wallet_raw or "").strip()
    key = str(key_raw or "").strip()
    use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "true").lower() == "true"
    # Approximate taker fee rate per side. Override in .env if needed.
    fee_rate = _to_float(os.getenv("HYPERLIQUID_TAKER_FEE_PCT", "0.00035"), 0.00035)

    result = {
        "mode": "testnet" if use_testnet else "mainnet",
        "execute": execute,
        "fee_rate": fee_rate,
        "min_net_pnl": min_net_pnl,
        "min_net_profit_pct": min_net_profit_pct,
        "hard_take_profit_pct": hard_take_profit_pct,
        "trailing_trigger_pct": trailing_trigger_pct,
        "trailing_retrace_pct": trailing_retrace_pct,
        "stop_loss_pct": stop_loss_pct,
        "max_net_loss_abs": max_net_loss_abs,
        "exit_slippage_pct": exit_slippage_pct,
        "only_production_positions": only_production_positions,
        "trailing_ladder": [],
        "trailing_profile": trailing_profile,
        "volatility_timeframe": volatility_timeframe,
        "volatility_lookback": volatility_lookback,
        "volatility_low_threshold_pct": volatility_low_threshold_pct,
        "volatility_high_threshold_pct": volatility_high_threshold_pct,
        "checked": [],
        "to_close": [],
        "closed": [],
        "errors": [],
    }

    if not wallet or not wallet.startswith("0x") or len(wallet) != 42:
        result["errors"].append("invalid_or_missing_wallet")
        return result
    if not key or not key.startswith("0x") or len(key) != 66:
        result["errors"].append("invalid_or_missing_signing_key")
        return result

    exchange = ccxt.hyperliquid({
        "walletAddress": wallet,
        "privateKey": key,
        "enableRateLimit": True,
        "options": {"defaultSlippage": 0.03},
    })
    if use_testnet:
        exchange.set_sandbox_mode(True)

    state = _load_state()
    trailing_ladder = _parse_trailing_ladder(trailing_ladder_raw)
    if not trailing_ladder:
        trailing_ladder = list(BALANCED_TRAILING_LADDER)
    symbol_volatility_cache: dict[str, float] = {}
    symbol_mark_cache: dict[str, float] = {}

    result["trailing_ladder"] = trailing_ladder

    production_targets = {"symbols": set(), "bases": set(), "bot_ids": set()}
    if only_production_positions:
        try:
            production_targets = _load_active_production_targets()
            result["production_targets"] = [
                {"bot_id": bot_id} for bot_id in sorted(production_targets.get("bot_ids") or set())
            ]
        except Exception as exc:
            result["errors"].append(f"production_targets_failed: {exc}")

    try:
        await exchange.load_markets()
        params = {"user": wallet} if wallet else {}
        positions = await exchange.fetch_positions(params=params)
        active_keys = set()

        for pos in positions:
            side, qty = _infer_side_qty(pos)
            if qty <= 0 or not side:
                continue

            symbol = pos.get("symbol")
            symbol_norm = str(symbol or "").strip().lower()
            symbol_base = _symbol_base(symbol)
            symbols = production_targets.get("symbols") or set()
            bases = production_targets.get("bases") or set()
            is_target_symbol = (symbol_norm in symbols) or (symbol_base in bases)
            if only_production_positions and not is_target_symbol:
                result["checked"].append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "close_reason": None,
                        "skipped": "not_active_production_position",
                    }
                )
                continue

            mark = _to_float(pos.get("markPrice") or (pos.get("info") or {}).get("markPx") or pos.get("lastPrice"))
            entry = _to_float(pos.get("entryPrice") or (pos.get("info") or {}).get("entryPx"))
            upnl = _to_float(pos.get("unrealizedPnl") or (pos.get("info") or {}).get("unrealizedPnl"))
            funding_pnl = _extract_funding_pnl(pos)

            # Some exchange snapshots return mark=0 for orphan/stale positions; fetch ticker once per symbol.
            if mark <= 0 and symbol:
                cached_mark = _to_float(symbol_mark_cache.get(symbol), 0.0)
                if cached_mark > 0:
                    mark = cached_mark
                else:
                    try:
                        ticker = await exchange.fetch_ticker(symbol)
                        mark = _to_float(ticker.get("last") or ticker.get("close") or ticker.get("mark"))
                        if mark > 0:
                            symbol_mark_cache[symbol] = mark
                    except Exception:
                        pass

            notional_entry = qty * (entry if entry > 0 else mark)
            notional_exit = qty * (mark if mark > 0 else entry)
            estimated_fee_entry = notional_entry * fee_rate if notional_entry > 0 else 0.0
            estimated_fee_exit = notional_exit * fee_rate if notional_exit > 0 else 0.0
            estimated_total_fees = estimated_fee_entry + estimated_fee_exit
            estimated_exit_slippage_cost = notional_exit * exit_slippage_pct if notional_exit > 0 else 0.0
            estimated_net_pnl = upnl - estimated_total_fees - estimated_exit_slippage_cost + funding_pnl
            estimated_net_profit_pct = (estimated_net_pnl / notional_entry) if notional_entry > 0 else 0.0
            gain_pct = _gain_pct(side, entry, mark)
            adverse_pct = max(0.0, -gain_pct)

            position_key = _position_key(symbol, side, qty, entry)
            active_keys.add(position_key)
            position_state = dict(state.get(position_key) or {})

            prev_best_price = _to_float(position_state.get("best_price"), mark)
            if side == "short":
                best_price = min(prev_best_price if prev_best_price > 0 else mark, mark) if mark > 0 else prev_best_price
            else:
                best_price = max(prev_best_price, mark)

            peak_gain_pct = max(_to_float(position_state.get("peak_gain_pct"), gain_pct), gain_pct)
            retrace_pct = _retrace_pct(side, best_price, mark)

            if symbol not in symbol_volatility_cache:
                symbol_volatility_cache[symbol] = await _estimate_volatility_pct(
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=volatility_timeframe,
                    lookback=volatility_lookback,
                )
            symbol_volatility_pct = _to_float(symbol_volatility_cache.get(symbol), 0.0)

            ladder_for_position, resolved_profile = _select_trailing_ladder(
                profile=trailing_profile,
                manual_ladder=trailing_ladder,
                symbol_volatility_pct=symbol_volatility_pct,
                vol_low_threshold_pct=volatility_low_threshold_pct,
                vol_high_threshold_pct=volatility_high_threshold_pct,
            )

            effective_trailing_retrace_pct = _resolve_trailing_retrace_pct(
                peak_gain_pct=peak_gain_pct,
                default_retrace_pct=trailing_retrace_pct,
                trailing_ladder=ladder_for_position,
            )

            dynamic_thresholds = _compute_dynamic_exit_thresholds(
                symbol_volatility_pct=symbol_volatility_pct,
                vol_low_threshold_pct=volatility_low_threshold_pct,
                vol_high_threshold_pct=volatility_high_threshold_pct,
                stop_loss_pct=stop_loss_pct,
                hard_take_profit_pct=hard_take_profit_pct,
                trailing_trigger_pct=trailing_trigger_pct,
                trailing_retrace_pct=effective_trailing_retrace_pct,
                min_net_pnl=min_net_pnl,
            )
            effective_stop_loss_pct = _to_float(dynamic_thresholds.get("effective_stop_loss_pct"), stop_loss_pct)
            effective_hard_take_profit_pct = _to_float(
                dynamic_thresholds.get("effective_hard_take_profit_pct"), hard_take_profit_pct
            )
            effective_trailing_trigger_pct = _to_float(
                dynamic_thresholds.get("effective_trailing_trigger_pct"), trailing_trigger_pct
            )
            effective_trailing_retrace_pct = _to_float(
                dynamic_thresholds.get("effective_trailing_retrace_pct"), effective_trailing_retrace_pct
            )
            breakeven_arm_gain_pct = _to_float(dynamic_thresholds.get("breakeven_arm_gain_pct"), 0.0)
            breakeven_min_net_pnl = _to_float(dynamic_thresholds.get("breakeven_min_net_pnl"), 0.0)

            close_reason = ""
            # Safety-first: cap downside before evaluating profit exits.
            if effective_stop_loss_pct > 0 and adverse_pct >= effective_stop_loss_pct:
                close_reason = "stop_loss_pct"
            elif (
                symbol_volatility_pct >= volatility_high_threshold_pct > 0
                and effective_stop_loss_pct > 0
                and adverse_pct >= (effective_stop_loss_pct * 0.65)
                and estimated_net_pnl < 0
            ):
                close_reason = "volatility_protective_stop"
            elif max_net_loss_abs > 0 and estimated_net_pnl <= -abs(max_net_loss_abs):
                close_reason = "max_net_loss_abs"
            elif estimated_net_pnl >= min_net_pnl and estimated_net_profit_pct >= min_net_profit_pct:
                if gain_pct >= effective_hard_take_profit_pct > 0:
                    close_reason = "hard_take_profit_pct"
                elif (
                    peak_gain_pct >= effective_trailing_trigger_pct > 0
                    and retrace_pct >= effective_trailing_retrace_pct > 0
                ):
                    close_reason = "trailing_take_profit"
            elif (
                peak_gain_pct >= breakeven_arm_gain_pct > 0
                and estimated_net_pnl <= breakeven_min_net_pnl
                and retrace_pct >= max(effective_trailing_retrace_pct * 0.75, 0.0015)
            ):
                close_reason = "breakeven_protect"

            position_state.update(
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": round(qty, 8),
                    "entry": round(entry, 8),
                    "best_price": round(best_price, 8),
                    "peak_gain_pct": round(peak_gain_pct, 8),
                    "last_mark": round(mark, 8),
                    "last_gain_pct": round(gain_pct, 8),
                    "last_retrace_pct": round(retrace_pct, 8),
                }
            )
            state[position_key] = position_state

            item = {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "entry": entry,
                "mark": mark,
                "gain_pct": round(gain_pct, 6),
                "adverse_pct": round(adverse_pct, 6),
                "best_price": round(best_price, 6),
                "peak_gain_pct": round(peak_gain_pct, 6),
                "retrace_pct": round(retrace_pct, 6),
                "effective_trailing_retrace_pct": round(effective_trailing_retrace_pct, 6),
                "effective_trailing_trigger_pct": round(effective_trailing_trigger_pct, 6),
                "effective_hard_take_profit_pct": round(effective_hard_take_profit_pct, 6),
                "effective_stop_loss_pct": round(effective_stop_loss_pct, 6),
                "breakeven_arm_gain_pct": round(breakeven_arm_gain_pct, 6),
                "breakeven_min_net_pnl": round(breakeven_min_net_pnl, 6),
                "trailing_profile_resolved": resolved_profile,
                "volatility_pct": round(symbol_volatility_pct, 6),
                "volatility_normalized": round(_to_float(dynamic_thresholds.get("volatility_normalized"), 0.0), 6),
                "trailing_ladder_used": ladder_for_position,
                "unrealized_pnl": upnl,
                "funding_pnl": round(funding_pnl, 6),
                "estimated_fee_entry": round(estimated_fee_entry, 6),
                "estimated_fee_exit": round(estimated_fee_exit, 6),
                "estimated_total_fees": round(estimated_total_fees, 6),
                "estimated_exit_slippage_cost": round(estimated_exit_slippage_cost, 6),
                "estimated_net_pnl": round(estimated_net_pnl, 6),
                "estimated_net_profit_pct": round(estimated_net_profit_pct, 6),
                "close_reason": close_reason or None,
            }
            result["checked"].append(item)

            if close_reason:
                result["to_close"].append(item)
                if execute:
                    close_side = "sell" if side == "long" else "buy"
                    try:
                        order_price = mark
                        if order_price <= 0:
                            ticker = await exchange.fetch_ticker(symbol)
                            order_price = _to_float(ticker.get("last") or ticker.get("close") or ticker.get("mark"))

                        order = await exchange.create_order(
                            symbol=symbol,
                            type="market",
                            side=close_side,
                            amount=qty,
                            price=order_price if order_price > 0 else None,
                            params={"reduceOnly": True},
                        )
                        result["closed"].append(
                            {
                                "symbol": symbol,
                                "qty": qty,
                                "original_side": side,
                                "unrealized_pnl": upnl,
                                "funding_pnl": round(funding_pnl, 6),
                                "estimated_total_fees": round(estimated_total_fees, 6),
                                "estimated_exit_slippage_cost": round(estimated_exit_slippage_cost, 6),
                                "estimated_net_pnl": round(estimated_net_pnl, 6),
                                "estimated_net_profit_pct": round(estimated_net_profit_pct, 6),
                                "gain_pct": round(gain_pct, 6),
                                "adverse_pct": round(adverse_pct, 6),
                                "peak_gain_pct": round(peak_gain_pct, 6),
                                "retrace_pct": round(retrace_pct, 6),
                                "effective_trailing_retrace_pct": round(effective_trailing_retrace_pct, 6),
                                "effective_trailing_trigger_pct": round(effective_trailing_trigger_pct, 6),
                                "effective_hard_take_profit_pct": round(effective_hard_take_profit_pct, 6),
                                "effective_stop_loss_pct": round(effective_stop_loss_pct, 6),
                                "breakeven_arm_gain_pct": round(breakeven_arm_gain_pct, 6),
                                "breakeven_min_net_pnl": round(breakeven_min_net_pnl, 6),
                                "trailing_profile_resolved": resolved_profile,
                                "volatility_pct": round(symbol_volatility_pct, 6),
                                "volatility_normalized": round(_to_float(dynamic_thresholds.get("volatility_normalized"), 0.0), 6),
                                "close_reason": close_reason,
                                "order_id": order.get("id"),
                                "status": order.get("status"),
                            }
                        )
                        state.pop(position_key, None)
                    except Exception as exc:
                        result["errors"].append(f"close {symbol}: {exc}")
        stale_keys = [key for key in state.keys() if key not in active_keys]
        for key in stale_keys:
            state.pop(key, None)
    except Exception as exc:
        result["errors"].append(str(exc))
    finally:
        try:
            await exchange.close()
        except Exception:
            pass
        try:
            _save_state(state)
        except Exception as exc:
            result["errors"].append(f"state_save_failed: {exc}")

    return result


async def watch(
    interval_sec: int,
    min_net_pnl: float,
    min_net_profit_pct: float,
    hard_take_profit_pct: float,
    trailing_trigger_pct: float,
    trailing_retrace_pct: float,
    stop_loss_pct: float,
    max_net_loss_abs: float,
    exit_slippage_pct: float,
    only_production_positions: bool,
    trailing_ladder_raw: str,
    trailing_profile: str,
    volatility_timeframe: str,
    volatility_lookback: int,
    volatility_low_threshold_pct: float,
    volatility_high_threshold_pct: float,
) -> None:
    while True:
        output = await run(
            execute=True,
            min_net_pnl=min_net_pnl,
            min_net_profit_pct=min_net_profit_pct,
            hard_take_profit_pct=hard_take_profit_pct,
            trailing_trigger_pct=trailing_trigger_pct,
            trailing_retrace_pct=trailing_retrace_pct,
            stop_loss_pct=stop_loss_pct,
            max_net_loss_abs=max_net_loss_abs,
            exit_slippage_pct=exit_slippage_pct,
            only_production_positions=only_production_positions,
            trailing_ladder_raw=trailing_ladder_raw,
            trailing_profile=trailing_profile,
            volatility_timeframe=volatility_timeframe,
            volatility_lookback=volatility_lookback,
            volatility_low_threshold_pct=volatility_low_threshold_pct,
            volatility_high_threshold_pct=volatility_high_threshold_pct,
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if output.get("closed"):
            # Stop after first successful protective/profit close.
            break
        errors = [str(e) for e in output.get("errors") or []]
        rate_limited = any("429" in e or "RateLimitExceeded" in e for e in errors)
        cumulative_request_blocked = any(
            "Too many cumulative requests sent" in e for e in errors
        )
        sleep_for = max(5, interval_sec)
        if rate_limited:
            sleep_for = max(sleep_for * 3, 60)
        if cumulative_request_blocked:
            # Exchange-side cumulative quota block; wait longer to avoid repeated rejected orders.
            sleep_for = max(sleep_for, 900)
        await asyncio.sleep(sleep_for)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Close profitable Hyperliquid positions")
    parser.add_argument("--execute", action="store_true", help="Actually close positions (default is dry-run)")
    parser.add_argument("--watch", action="store_true", help="Watch continuously and close when profitable")
    parser.add_argument("--interval", type=int, default=20, help="Seconds between checks in watch mode")
    parser.add_argument(
        "--min-net-pnl",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_MIN_NET_PNL", "1.0"), 1.0),
        help="Minimum estimated net PnL (after fees) required to close",
    )
    parser.add_argument(
        "--hard-take-profit-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_HARD_TAKE_PROFIT_PCT", "0.05"), 0.05),
        help="Close immediately when gain from entry reaches this percentage (e.g. 0.05 = 5%%)",
    )
    parser.add_argument(
        "--min-net-profit-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_MIN_NET_PROFIT_PCT", "0.0"), 0.0),
        help="Minimum estimated net profit percentage after fees/slippage/funding required to close",
    )
    parser.add_argument(
        "--trailing-trigger-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_TRAILING_TRIGGER_PCT", "0.02"), 0.02),
        help="Arm trailing take-profit after this gain percentage from entry",
    )
    parser.add_argument(
        "--trailing-retrace-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_TRAILING_RETRACE_PCT", "0.0075"), 0.0075),
        help="Close when price retraces this percentage from the best favorable price after trailing is armed",
    )
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_STOP_LOSS_PCT", "0.02"), 0.02),
        help="Close when adverse move from entry reaches this percentage (e.g. 0.02 = 2%%). Set 0 to disable",
    )
    parser.add_argument(
        "--max-net-loss-abs",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_MAX_NET_LOSS_ABS", "3.0"), 3.0),
        help="Close when estimated net PnL goes below this absolute loss in quote currency. Set 0 to disable",
    )
    parser.add_argument(
        "--exit-slippage-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_EXIT_SLIPPAGE_PCT", "0.0002"), 0.0002),
        help="Estimated market-impact/slippage percentage for exit order cost",
    )
    parser.add_argument(
        "--only-production-positions",
        action=argparse.BooleanOptionalAction,
        default=_to_bool(os.getenv("HYPERLIQUID_TP_ONLY_PRODUCTION", "true"), True),
        help="Only evaluate positions linked to active production bots",
    )
    parser.add_argument(
        "--trailing-ladder",
        type=str,
        default=os.getenv(
            "HYPERLIQUID_TRAILING_LADDER",
            "0.02:0.0075,0.05:0.006,0.10:0.0045",
        ),
        help=(
            "Adaptive trailing retrace ladder as gain:retrace list. "
            "Example: 0.02:0.0075,0.05:0.006,0.10:0.0045"
        ),
    )
    parser.add_argument(
        "--trailing-profile",
        choices=["manual", "conservative", "aggressive", "auto"],
        default=os.getenv("HYPERLIQUID_TRAILING_PROFILE", "manual"),
        help=(
            "Trailing profile mode. manual uses --trailing-ladder; "
            "auto switches between conservative/aggressive based on volatility"
        ),
    )
    parser.add_argument(
        "--volatility-timeframe",
        type=str,
        default=os.getenv("HYPERLIQUID_VOLATILITY_TIMEFRAME", "5m"),
        help="OHLCV timeframe used for volatility estimate in auto profile",
    )
    parser.add_argument(
        "--volatility-lookback",
        type=int,
        default=int(os.getenv("HYPERLIQUID_VOLATILITY_LOOKBACK", "48")),
        help="Number of candles used to estimate volatility in auto profile",
    )
    parser.add_argument(
        "--volatility-low-threshold-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_VOLATILITY_LOW_THRESHOLD_PCT", "0.0015"), 0.0015),
        help="Auto profile low-volatility threshold",
    )
    parser.add_argument(
        "--volatility-high-threshold-pct",
        type=float,
        default=_to_float(os.getenv("HYPERLIQUID_VOLATILITY_HIGH_THRESHOLD_PCT", "0.0035"), 0.0035),
        help="Auto profile high-volatility threshold",
    )
    args = parser.parse_args()

    if args.watch:
        asyncio.run(
            watch(
                interval_sec=args.interval,
                min_net_pnl=args.min_net_pnl,
                min_net_profit_pct=args.min_net_profit_pct,
                hard_take_profit_pct=args.hard_take_profit_pct,
                trailing_trigger_pct=args.trailing_trigger_pct,
                trailing_retrace_pct=args.trailing_retrace_pct,
                stop_loss_pct=args.stop_loss_pct,
                max_net_loss_abs=args.max_net_loss_abs,
                exit_slippage_pct=args.exit_slippage_pct,
                only_production_positions=args.only_production_positions,
                trailing_ladder_raw=args.trailing_ladder,
                trailing_profile=args.trailing_profile,
                volatility_timeframe=args.volatility_timeframe,
                volatility_lookback=args.volatility_lookback,
                volatility_low_threshold_pct=args.volatility_low_threshold_pct,
                volatility_high_threshold_pct=args.volatility_high_threshold_pct,
            )
        )
    else:
        output = asyncio.run(
            run(
                execute=args.execute,
                min_net_pnl=args.min_net_pnl,
                min_net_profit_pct=args.min_net_profit_pct,
                hard_take_profit_pct=args.hard_take_profit_pct,
                trailing_trigger_pct=args.trailing_trigger_pct,
                trailing_retrace_pct=args.trailing_retrace_pct,
                stop_loss_pct=args.stop_loss_pct,
                max_net_loss_abs=args.max_net_loss_abs,
                exit_slippage_pct=args.exit_slippage_pct,
                only_production_positions=args.only_production_positions,
                trailing_ladder_raw=args.trailing_ladder,
                trailing_profile=args.trailing_profile,
                volatility_timeframe=args.volatility_timeframe,
                volatility_lookback=args.volatility_lookback,
                volatility_low_threshold_pct=args.volatility_low_threshold_pct,
                volatility_high_threshold_pct=args.volatility_high_threshold_pct,
            )
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
