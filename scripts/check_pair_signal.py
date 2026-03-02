import asyncio
import json

import requests

from apps.engine.market_data import MarketDataEngine
from apps.engine.paired_balanced import PairedBalancedStrategy


async def main():
    base = "http://localhost:8000"
    data = requests.get(f"{base}/api/bots", timeout=10).json()
    bots = data if isinstance(data, list) else data.get("bots", [])
    bot = next((x for x in bots if x.get("id") == "Bot-LAB-PAIR-BTC-ETH"), None)
    if not bot:
        raise RuntimeError("Bot-LAB-PAIR-BTC-ETH not found")

    cfg = dict(bot.get("config") or {})
    symbol_a = cfg.get("pair_symbol_a") or cfg.get("symbol") or "BTC/USDT"
    symbol_b = cfg.get("pair_symbol_b") or "ETH/USDT"
    lookback = int(cfg.get("pair_lookback", 120) or 120)

    mde = MarketDataEngine("binance")
    history_a = await mde.fetch_ohlcv(symbol_a, limit=lookback + 20)
    history_b = await mde.fetch_ohlcv(symbol_b, limit=lookback + 20)
    await mde.close()

    strategy = PairedBalancedStrategy(lookback=lookback)
    decision = strategy.evaluate(
        {
            "history_a": history_a,
            "history_b": history_b,
            "entry_z": float(cfg.get("pair_entry_z", 1.4) or 1.4),
            "exit_z": float(cfg.get("pair_exit_z", 0.25) or 0.25),
            "min_correlation": float(cfg.get("pair_min_correlation", 0.35) or 0.35),
            "enable_cadf": bool(cfg.get("pair_enable_cadf", True)),
            "cadf_alpha": float(cfg.get("pair_cadf_alpha", 0.05) or 0.05),
        }
    )

    out = {
        "bot_status": bot.get("status"),
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        "pair_entry_z": cfg.get("pair_entry_z"),
        "pair_exit_z": cfg.get("pair_exit_z"),
        "pair_min_correlation": cfg.get("pair_min_correlation"),
        "pair_lookback": lookback,
        "pair_enable_cadf": cfg.get("pair_enable_cadf", True),
        "pair_cadf_alpha": cfg.get("pair_cadf_alpha", 0.05),
        "decision": decision.action,
        "reason": decision.reason,
        "zscore": round(float(decision.zscore), 6),
        "correlation": round(float(decision.correlation), 6),
        "cadf_passed": decision.cadf_passed,
        "cadf_pvalue": (round(float(decision.cadf_pvalue), 8) if decision.cadf_pvalue is not None else None),
        "cadf_stat": (round(float(decision.cadf_stat), 6) if decision.cadf_stat is not None else None),
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
