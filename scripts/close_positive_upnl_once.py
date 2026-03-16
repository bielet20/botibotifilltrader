import asyncio
import json
import os

import ccxt.async_support as ccxt


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


async def main() -> None:
    exchange = ccxt.hyperliquid(
        {
            "walletAddress": os.getenv("HYPERLIQUID_WALLET_ADDRESS", ""),
            "privateKey": os.getenv("HYPERLIQUID_SIGNING_KEY", ""),
            "enableRateLimit": True,
        }
    )

    if os.getenv("HYPERLIQUID_USE_TESTNET", "true").lower() == "true":
        exchange.set_sandbox_mode(True)

    out = {"checked": [], "closed": [], "errors": []}

    try:
        await exchange.load_markets()
        wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
        params = {"user": wallet} if wallet else {}
        positions = await exchange.fetch_positions(params=params)

        for p in positions:
            size = _to_float(p.get("contracts") or p.get("info", {}).get("size"))
            if size == 0:
                continue

            symbol = p.get("symbol")
            side_raw = str(p.get("side") or "").strip().lower()
            if side_raw in {"long", "short"}:
                side = side_raw
            else:
                side = "long" if size > 0 else "short"
            qty = abs(size)
            upnl = _to_float(p.get("unrealizedPnl") or p.get("info", {}).get("unrealizedPnl"))
            mark = _to_float(p.get("markPrice") or p.get("info", {}).get("markPx") or p.get("lastPrice"))

            out["checked"].append(
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "upnl": upnl,
                    "mark": mark,
                }
            )

            if upnl <= 0:
                continue

            close_side = "sell" if side == "long" else "buy"
            try:
                if mark <= 0:
                    ticker = await exchange.fetch_ticker(symbol)
                    mark = _to_float(ticker.get("last") or ticker.get("close") or ticker.get("mark"))

                order = await exchange.create_order(
                    symbol=symbol,
                    type="market",
                    side=close_side,
                    amount=qty,
                    price=mark if mark > 0 else None,
                    params={"reduceOnly": True, "timeInForce": "Ioc"},
                )
                out["closed"].append(
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "upnl": upnl,
                        "order_id": order.get("id"),
                        "status": order.get("status"),
                    }
                )
            except Exception as exc:
                out["errors"].append(f"close {symbol}: {exc}")
    finally:
        await exchange.close()

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
