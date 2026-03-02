import asyncio
import argparse
import os
import sys
import json
import urllib.request
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.shared.models import TradeSignal, TradeSide, TradeDB
from apps.shared.database import SessionLocal


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _public_account_value(wallet: str, use_testnet: bool) -> float:
    url = "https://api.hyperliquid-testnet.xyz/info" if use_testnet else "https://api.hyperliquid.xyz/info"
    payload = json.dumps({"type": "clearinghouseState", "user": wallet}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    margin = data.get("marginSummary") or {}
    return float(margin.get("accountValue") or 0.0)


async def run_roundtrip(
    symbol: str = "BTC/USDC:USDC",
    amount: float = 0.0002,
    bot_id: str = "Bot-571",
    force_mainnet: bool = False,
):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(dotenv_path=os.path.join(project_root, ".env"))

    use_testnet = _bool_env("HYPERLIQUID_USE_TESTNET", True)
    if force_mainnet:
        use_testnet = False

    if not use_testnet and not force_mainnet:
        raise RuntimeError("Mainnet deshabilitada por seguridad. Usa --mainnet para confirmarlo explícitamente.")

    wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
    signing_key = os.getenv("HYPERLIQUID_SIGNING_KEY", "")

    if not HyperliquidExecutor._is_valid_wallet(wallet):
        raise RuntimeError("HYPERLIQUID_WALLET_ADDRESS inválida o ausente")
    if not HyperliquidExecutor._is_valid_private_key(signing_key):
        raise RuntimeError("HYPERLIQUID_SIGNING_KEY inválida o placeholder (requiere 0x + 64 hex)")

    account_value = _public_account_value(wallet, use_testnet)
    if account_value <= 0:
        env_name = "TESTNET" if use_testnet else "MAINNET"
        raise RuntimeError(f"Sin fondos detectados en {env_name} para la wallet (accountValue={account_value})")

    executor = HyperliquidExecutor(use_testnet=use_testnet)

    if not executor.is_configured:
        raise RuntimeError("Credenciales Hyperliquid no configuradas")

    try:
        buy_signal = TradeSignal(
            strategy_id="MANUAL_TESTNET_ROUNDTRIP",
            symbol=symbol,
            side=TradeSide.BUY,
            amount=amount,
            price=None,
            meta={"source": "manual_testnet"},
        )

        env_name = "TESTNET" if use_testnet else "MAINNET"
        print(f"[{env_name}] BUY {amount} {symbol}")
        buy_exec = await executor.execute(buy_signal)
        if buy_exec.status == "failed":
            raise RuntimeError("Falló la orden de compra")

        await asyncio.sleep(2)

        sell_signal = TradeSignal(
            strategy_id="MANUAL_TESTNET_ROUNDTRIP",
            symbol=symbol,
            side=TradeSide.SELL,
            amount=buy_exec.filled_amount,
            price=None,
            meta={"source": "manual_testnet"},
        )

        print(f"[{env_name}] SELL {buy_exec.filled_amount} {symbol}")
        sell_exec = await executor.execute(sell_signal)
        if sell_exec.status == "failed":
            raise RuntimeError("Falló la orden de venta")

        gross_pnl = (sell_exec.avg_price - buy_exec.avg_price) * sell_exec.filled_amount
        total_fees = float(getattr(buy_exec, 'fee', 0.0) or 0.0) + float(getattr(sell_exec, 'fee', 0.0) or 0.0)
        net_pnl = gross_pnl - total_fees

        with SessionLocal() as db:
            db.add(TradeDB(
                bot_id=bot_id,
                symbol=symbol,
                side=TradeSide.BUY,
                price=buy_exec.avg_price,
                amount=buy_exec.filled_amount,
                fee=float(getattr(buy_exec, 'fee', 0.0) or 0.0),
                pnl=0.0,
                time=datetime.utcnow(),
                meta={"source": "manual_testnet", "order_id": buy_exec.order_id},
            ))

            db.add(TradeDB(
                bot_id=bot_id,
                symbol=symbol,
                side=TradeSide.SELL,
                price=sell_exec.avg_price,
                amount=sell_exec.filled_amount,
                fee=float(getattr(sell_exec, 'fee', 0.0) or 0.0),
                pnl=gross_pnl,
                time=datetime.utcnow(),
                meta={"source": "manual_testnet", "order_id": sell_exec.order_id},
            ))

            db.commit()

        print("[RESULT]", {
            "env": env_name,
            "buy_price": buy_exec.avg_price,
            "sell_price": sell_exec.avg_price,
            "qty": sell_exec.filled_amount,
            "gross_pnl": round(gross_pnl, 8),
            "fees": round(total_fees, 8),
            "net_pnl": round(net_pnl, 8),
            "buy_order_id": buy_exec.order_id,
            "sell_order_id": sell_exec.order_id,
        })
    finally:
        await executor.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roundtrip manual Hyperliquid (testnet/mainnet)")
    parser.add_argument("--symbol", default="BTC/USDC:USDC")
    parser.add_argument("--amount", type=float, default=0.0002)
    parser.add_argument("--bot-id", default="Bot-571")
    parser.add_argument("--mainnet", action="store_true", help="Forzar ejecución en mainnet")
    args = parser.parse_args()

    asyncio.run(
        run_roundtrip(
            symbol=args.symbol,
            amount=args.amount,
            bot_id=args.bot_id,
            force_mainnet=args.mainnet,
        )
    )
