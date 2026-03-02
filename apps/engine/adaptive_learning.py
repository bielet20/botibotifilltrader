from statistics import pstdev
import time

from apps.shared.interfaces import BaseStrategy
from apps.shared.models import TradeSignal, TradeSide


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))


class AdaptiveLearningStrategy(BaseStrategy):
    """
    Estrategia adaptativa (MVP):
    - Lee histórico OHLCV y detecta tendencia + momentum.
    - Ajusta sensibilidad según volatilidad reciente.
    - Ajusta tamaño de orden según nivel de confianza.
    """

    def __init__(
        self,
        short_window: int = 12,
        long_window: int = 48,
        base_amount: float = 0.01,
        min_threshold: float = 0.001,
        max_threshold: float = 0.01,
    ):
        self.short_window = max(6, int(short_window))
        self.long_window = max(self.short_window + 6, int(long_window))
        self.base_amount = max(0.001, float(base_amount))
        self.min_threshold = max(0.0005, float(min_threshold))
        self.max_threshold = max(self.min_threshold + 0.001, float(max_threshold))

    async def analyze(self, market_data: dict) -> TradeSignal:
        symbol = market_data.get("symbol", "BTC/USDT")
        price = float(market_data.get("last_price") or 0.0)
        allocation = float(market_data.get("allocation") or 0.0)
        history = market_data.get("history") or []
        learning_state = dict(market_data.get("learning_state") or {})
        portfolio = dict(market_data.get("portfolio") or {})
        min_flip_move_pct = float(market_data.get("adaptive_min_flip_move_pct") or 0.0012)
        min_reentry_move_pct = float(market_data.get("adaptive_min_reentry_move_pct") or 0.0008)
        min_flip_interval_sec = float(market_data.get("adaptive_min_flip_interval_sec") or 45.0)
        bootstrap_unlock_sec = float(market_data.get("adaptive_bootstrap_unlock_sec") or 2700.0)
        bootstrap_probe_interval_sec = float(market_data.get("adaptive_bootstrap_probe_interval_sec") or 1800.0)

        required = self.long_window + 2
        if price <= 0 or len(history) < required:
            return TradeSignal(
                symbol=symbol,
                side=TradeSide.HOLD,
                amount=0,
                price=price if price > 0 else None,
                strategy_id="Adaptive_Learning_v1",
                meta={"reason": "insufficient_history", "required": required, "received": len(history)},
            )

        closes = [float(c.get("close", 0.0) or 0.0) for c in history if float(c.get("close", 0.0) or 0.0) > 0]
        if len(closes) < required:
            return TradeSignal(
                symbol=symbol,
                side=TradeSide.HOLD,
                amount=0,
                price=price,
                strategy_id="Adaptive_Learning_v1",
                meta={"reason": "invalid_closes", "required": required, "received": len(closes)},
            )

        short_ma = sum(closes[-self.short_window:]) / self.short_window
        long_ma = sum(closes[-self.long_window:]) / self.long_window
        trend_strength = ((short_ma - long_ma) / long_ma) if long_ma else 0.0

        momentum_period = min(6, self.short_window - 1)
        past_price = closes[-(momentum_period + 1)]
        momentum = ((closes[-1] - past_price) / past_price) if past_price else 0.0

        returns = []
        for i in range(max(1, len(closes) - self.long_window), len(closes)):
            prev = closes[i - 1]
            cur = closes[i]
            if prev > 0:
                returns.append((cur - prev) / prev)

        volatility = float(pstdev(returns)) if len(returns) > 1 else 0.0

        adaptive_threshold = _clamp(
            self.min_threshold + (volatility * 1.5),
            self.min_threshold,
            self.max_threshold,
        )

        previous_threshold = float(learning_state.get("adaptive_threshold", adaptive_threshold) or adaptive_threshold)
        adaptive_threshold = _clamp((previous_threshold * 0.7) + (adaptive_threshold * 0.3), self.min_threshold, self.max_threshold)

        confidence = abs(trend_strength) * 0.65 + abs(momentum) * 0.35
        total_trades = int(learning_state.get("total_trades", 0) or 0)
        win_rate = float(learning_state.get("win_rate", 50.0) or 50.0)
        cumulative_pnl = float(learning_state.get("cumulative_pnl", 0.0) or 0.0)

        experience_factor = _clamp(1.0 + min(total_trades, 200) / 1000.0, 1.0, 1.2)
        win_rate_factor = _clamp(1.0 + ((win_rate - 50.0) / 200.0), 0.85, 1.15)
        pnl_factor = _clamp(1.0 + (cumulative_pnl / 5000.0), 0.8, 1.2)
        confidence = confidence * experience_factor * win_rate_factor
        if confidence < adaptive_threshold:
            new_state = dict(learning_state)
            new_state.update({
                "adaptive_threshold": round(adaptive_threshold * 0.995, 8),
                "last_confidence": round(confidence, 8),
                "last_volatility": round(volatility, 8),
                "last_side": "hold",
            })
            return TradeSignal(
                symbol=symbol,
                side=TradeSide.HOLD,
                amount=0,
                price=price,
                strategy_id="Adaptive_Learning_v1",
                meta={
                    "reason": "low_confidence",
                    "trend": round(trend_strength, 6),
                    "momentum": round(momentum, 6),
                    "volatility": round(volatility, 6),
                    "confidence": round(confidence, 6),
                    "threshold": round(adaptive_threshold, 6),
                    "experience_factor": round(experience_factor, 6),
                    "win_rate_factor": round(win_rate_factor, 6),
                    "pnl_factor": round(pnl_factor, 6),
                    "learning_state": new_state,
                },
            )

        side = TradeSide.BUY if trend_strength >= 0 and momentum >= 0 else TradeSide.SELL

        positions = dict(portfolio.get("positions") or {})
        position_for_symbol = dict(positions.get(symbol) or {})
        current_amount = float(position_for_symbol.get("amount") or 0.0)
        allow_short = bool(market_data.get("allow_short", False))
        last_exec_side = str(learning_state.get("last_exec_side", "") or "").lower()
        last_exec_price = float(learning_state.get("last_exec_price", 0.0) or 0.0)
        last_exec_at = float(learning_state.get("last_exec_at", 0.0) or 0.0)
        last_bootstrap_probe_at = float(learning_state.get("last_bootstrap_probe_at", 0.0) or 0.0)
        last_realized_pnl = float(learning_state.get("last_realized_pnl", 0.0) or 0.0)
        loss_streak = int(learning_state.get("loss_streak", 0) or 0)
        bootstrap_locked = bool(learning_state.get("bootstrap_locked", False))

        if loss_streak >= 3:
            bootstrap_locked = True

        if bootstrap_locked and last_exec_side == "sell" and last_realized_pnl > 0:
            bootstrap_locked = False

        if last_exec_at > 0 and side.value != last_exec_side and last_exec_side:
            elapsed = max(0.0, float(time.time()) - last_exec_at)
            if elapsed < max(0.0, min_flip_interval_sec):
                new_state = dict(learning_state)
                new_state.update({
                    "last_confidence": round(confidence, 8),
                    "last_volatility": round(volatility, 8),
                    "last_side": "hold",
                })
                return TradeSignal(
                    symbol=symbol,
                    side=TradeSide.HOLD,
                    amount=0,
                    price=price,
                    strategy_id="Adaptive_Learning_v1",
                    meta={
                        "reason": "flip_guard_cooldown",
                        "elapsed_sec": round(elapsed, 3),
                        "min_flip_interval_sec": round(min_flip_interval_sec, 3),
                        "last_exec_side": last_exec_side,
                        "learning_state": new_state,
                    },
                )

        if last_exec_price > 0 and side.value != last_exec_side:
            flip_move_pct = abs(price - last_exec_price) / last_exec_price
            if flip_move_pct < max(0.0, min_flip_move_pct):
                new_state = dict(learning_state)
                new_state.update({
                    "last_confidence": round(confidence, 8),
                    "last_volatility": round(volatility, 8),
                    "last_side": "hold",
                })
                return TradeSignal(
                    symbol=symbol,
                    side=TradeSide.HOLD,
                    amount=0,
                    price=price,
                    strategy_id="Adaptive_Learning_v1",
                    meta={
                        "reason": "flip_guard_min_move",
                        "flip_move_pct": round(flip_move_pct, 6),
                        "min_flip_move_pct": round(min_flip_move_pct, 6),
                        "last_exec_side": last_exec_side,
                        "last_exec_price": round(last_exec_price, 6),
                        "learning_state": new_state,
                    },
                )

        if side == TradeSide.BUY and current_amount > 0 and last_exec_price > 0:
            reentry_move_pct = abs(price - last_exec_price) / last_exec_price
            if reentry_move_pct < max(0.0, min_reentry_move_pct):
                new_state = dict(learning_state)
                new_state.update({
                    "last_confidence": round(confidence, 8),
                    "last_volatility": round(volatility, 8),
                    "last_side": "hold",
                })
                return TradeSignal(
                    symbol=symbol,
                    side=TradeSide.HOLD,
                    amount=0,
                    price=price,
                    strategy_id="Adaptive_Learning_v1",
                    meta={
                        "reason": "reentry_guard_min_move",
                        "reentry_move_pct": round(reentry_move_pct, 6),
                        "min_reentry_move_pct": round(min_reentry_move_pct, 6),
                        "position_amount": round(current_amount, 8),
                        "last_exec_price": round(last_exec_price, 6),
                        "learning_state": new_state,
                    },
                )

        bootstrap_long = False
        bootstrap_probe = False
        if side == TradeSide.SELL and current_amount <= 0 and not allow_short:
            if bootstrap_locked:
                now_ts = float(time.time())
                elapsed_from_exec = max(0.0, now_ts - last_exec_at) if last_exec_at > 0 else 0.0
                elapsed_from_probe = max(0.0, now_ts - last_bootstrap_probe_at) if last_bootstrap_probe_at > 0 else 10**9

                probe_conf_ok = confidence >= (adaptive_threshold * 1.25)
                probe_trend_ok = trend_strength >= 0
                probe_momentum_ok = momentum >= -(adaptive_threshold * 0.1)
                probe_time_ok = elapsed_from_exec >= max(60.0, bootstrap_unlock_sec)
                probe_interval_ok = elapsed_from_probe >= max(60.0, bootstrap_probe_interval_sec)

                if probe_conf_ok and probe_trend_ok and probe_momentum_ok and probe_time_ok and probe_interval_ok:
                    side = TradeSide.BUY
                    bootstrap_long = True
                    bootstrap_probe = True
                else:
                    new_state = dict(learning_state)
                    new_state.update({
                        "adaptive_threshold": round(adaptive_threshold * 0.997, 8),
                        "last_confidence": round(confidence, 8),
                        "last_volatility": round(volatility, 8),
                        "last_side": "hold",
                        "position_amount": round(current_amount, 8),
                        "bootstrap_locked": True,
                    })
                    return TradeSignal(
                        symbol=symbol,
                        side=TradeSide.HOLD,
                        amount=0,
                        price=price,
                        strategy_id="Adaptive_Learning_v1",
                        meta={
                            "reason": "bootstrap_locked_until_profitable_sell",
                            "loss_streak": loss_streak,
                            "elapsed_from_exec_sec": round(elapsed_from_exec, 3),
                            "bootstrap_unlock_sec": round(bootstrap_unlock_sec, 3),
                            "elapsed_from_probe_sec": round(elapsed_from_probe, 3),
                            "bootstrap_probe_interval_sec": round(bootstrap_probe_interval_sec, 3),
                            "last_exec_side": last_exec_side,
                            "last_realized_pnl": round(last_realized_pnl, 8),
                            "learning_state": new_state,
                        },
                    )

            bootstrap_conf_ok = confidence >= (adaptive_threshold * 1.2)
            bootstrap_trend_ok = trend_strength >= (adaptive_threshold * 0.2)
            bootstrap_momentum_ok = momentum >= -(adaptive_threshold * 0.2)

            if bootstrap_conf_ok and bootstrap_trend_ok and bootstrap_momentum_ok:
                side = TradeSide.BUY
                bootstrap_long = True
            else:
                new_state = dict(learning_state)
                new_state.update({
                    "adaptive_threshold": round(adaptive_threshold * 0.997, 8),
                    "last_confidence": round(confidence, 8),
                    "last_volatility": round(volatility, 8),
                    "last_side": "hold",
                    "position_amount": round(current_amount, 8),
                    "bootstrap_locked": bootstrap_locked,
                })
                return TradeSignal(
                    symbol=symbol,
                    side=TradeSide.HOLD,
                    amount=0,
                    price=price,
                    strategy_id="Adaptive_Learning_v1",
                    meta={
                        "reason": "no_long_position_for_sell",
                        "trend": round(trend_strength, 6),
                        "momentum": round(momentum, 6),
                        "volatility": round(volatility, 6),
                        "confidence": round(confidence, 6),
                        "threshold": round(adaptive_threshold, 6),
                        "position_amount": round(current_amount, 8),
                        "bootstrap_conf_ok": bootstrap_conf_ok,
                        "bootstrap_trend_ok": bootstrap_trend_ok,
                        "bootstrap_momentum_ok": bootstrap_momentum_ok,
                        "learning_state": new_state,
                    },
                )

        vol_risk_factor = _clamp(1.0 - (volatility * 8.0), 0.35, 1.2)
        confidence_factor = _clamp(confidence / adaptive_threshold, 1.0, 2.0)
        amount = self.base_amount * vol_risk_factor * confidence_factor * pnl_factor

        if bootstrap_long:
            amount *= 0.25
        if bootstrap_probe:
            amount *= 0.4

        if side == TradeSide.SELL and current_amount > 0 and not allow_short:
            amount = min(amount, current_amount)

        if allocation > 0 and price > 0:
            max_affordable_amount = (allocation * 0.9) / price
            amount = min(amount, max_affordable_amount)

        if amount <= 0:
            return TradeSignal(
                symbol=symbol,
                side=TradeSide.HOLD,
                amount=0,
                price=price,
                strategy_id="Adaptive_Learning_v1",
                meta={
                    "reason": "non_positive_amount",
                    "allocation": round(allocation, 6),
                    "base_amount": self.base_amount,
                },
            )

        tighten = 1.005 if side == TradeSide.SELL else 0.998
        new_state = dict(learning_state)
        new_state.update({
            "adaptive_threshold": round(_clamp(adaptive_threshold * tighten, self.min_threshold, self.max_threshold), 8),
            "last_confidence": round(confidence, 8),
            "last_volatility": round(volatility, 8),
            "last_side": side.value,
            "last_amount": round(amount, 8),
            "bootstrap_locked": bootstrap_locked,
            "last_bootstrap_probe_at": round(float(time.time()), 3) if bootstrap_probe else last_bootstrap_probe_at,
        })

        return TradeSignal(
            symbol=symbol,
            side=side,
            amount=round(amount, 6),
            price=price,
            strategy_id="Adaptive_Learning_v1",
            meta={
                "trend": round(trend_strength, 6),
                "momentum": round(momentum, 6),
                "volatility": round(volatility, 6),
                "confidence": round(confidence, 6),
                "threshold": round(adaptive_threshold, 6),
                "bootstrap_long": bootstrap_long,
                "bootstrap_probe": bootstrap_probe,
                "short_window": self.short_window,
                "long_window": self.long_window,
                "base_amount": self.base_amount,
                "experience_factor": round(experience_factor, 6),
                "win_rate_factor": round(win_rate_factor, 6),
                "pnl_factor": round(pnl_factor, 6),
                "learning_state": new_state,
            },
        )
