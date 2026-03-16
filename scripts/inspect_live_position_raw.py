import asyncio
import json
import os

import ccxt.async_support as ccxt


async def main() -> None:
    ex = ccxt.hyperliquid(
        {
            "walletAddress": os.getenv("HYPERLIQUID_WALLET_ADDRESS", ""),
            "privateKey": os.getenv("HYPERLIQUID_SIGNING_KEY", ""),
            "enableRateLimit": True,
        }
    )
    if os.getenv("HYPERLIQUID_USE_TESTNET", "true").lower() == "true":
        ex.set_sandbox_mode(True)

    try:
        await ex.load_markets()
        wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
        positions = await ex.fetch_positions(params={"user": wallet} if wallet else {})
        out = []
        for p in positions:
            contracts = p.get("contracts")
            info = p.get("info") or {}
            size = info.get("size")
            side = p.get("side")
            symbol = p.get("symbol")
            upnl = p.get("unrealizedPnl")
            mark = p.get("markPrice")
            out.append(
                {
                    "symbol": symbol,
                    "contracts": contracts,
                    "side": side,
                    "markPrice": mark,
                    "unrealizedPnl": upnl,
                    "info_size": size,
                    "info": {
                        "coin": info.get("coin"),
                        "szi": info.get("szi"),
                        "size": info.get("size"),
                        "position": info.get("position"),
                    },
                }
            )
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        await ex.close()


if __name__ == "__main__":
    asyncio.run(main())
