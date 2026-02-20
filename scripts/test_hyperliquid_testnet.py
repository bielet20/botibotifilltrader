"""
Test de trades en vivo en la Testnet de Hyperliquid.
Ejecuta un ciclo de BUY y luego SELL para verificar la ejecución real.
"""
import asyncio
import os
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

import ccxt.async_support as ccxt
from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.shared.models import TradeSignal, TradeSide

SYMBOL = "BTC/USDC:USDC"
AMOUNT = 0.001  # Mínimo posible para prueba (~$67)

async def test_testnet_trades():
    print("=" * 55)
    print("  HYPERLIQUID TESTNET — TEST DE TRADES EN VIVO")
    print("=" * 55)

    wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
    key    = os.getenv("HYPERLIQUID_SIGNING_KEY")
    testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"

    print(f"  Wallet : {wallet}")
    print(f"  Red    : {'TESTNET ✓' if testnet else 'MAINNET ⚠'}")
    print(f"  Par    : {SYMBOL}  |  Qty: {AMOUNT}")
    print()

    # ── Conexión de diagnóstico ──────────────────────────────────
    exch = ccxt.hyperliquid({'privateKey': key, 'walletAddress': wallet})
    if testnet:
        exch.set_sandbox_mode(True)

    try:
        balance = await exch.fetch_balance()
        usdc = balance.get('USDC', {}).get('total', 0)
        print(f"[INFO] Balance Testnet: {usdc:.2f} USDC")
    except Exception as e:
        print(f"[WARN] No se pudo leer el balance: {e}")
    finally:
        await exch.close()

    # ── Test BUY ─────────────────────────────────────────────────
    print("\n[1/2] Enviando orden BUY …")
    executor = HyperliquidExecutor()
    ticker = await executor.exchange.fetch_ticker(SYMBOL)
    price = ticker['last']
    print(f"      Precio actual: ${price:,.2f}")

    buy_signal = TradeSignal(
        symbol=SYMBOL,
        side=TradeSide.BUY,
        amount=AMOUNT,
        price=price,
        strategy_id="testnet_live_test"
    )

    buy_result = await executor.execute(buy_signal)
    print(f"      → orden_id : {buy_result.order_id}")
    print(f"      → estado   : {buy_result.status}")
    print(f"      → precio   : ${buy_result.avg_price:,.2f}")
    print(f"      → cantidad : {buy_result.filled_amount}")

    if buy_result.status == "failed":
        print("\n[✗] El BUY falló. Revisa que la cuenta tenga USDC en la Testnet.")
        return

    # ── Test SELL ────────────────────────────────────────────────
    print("\n[2/2] Enviando orden SELL …")
    sell_executor = HyperliquidExecutor()
    ticker2 = await sell_executor.exchange.fetch_ticker(SYMBOL)
    price2 = ticker2['last']

    sell_signal = TradeSignal(
        symbol=SYMBOL,
        side=TradeSide.SELL,
        amount=buy_result.filled_amount or AMOUNT,
        price=price2,
        strategy_id="testnet_live_test"
    )

    sell_result = await sell_executor.execute(sell_signal)
    print(f"      → orden_id : {sell_result.order_id}")
    print(f"      → estado   : {sell_result.status}")
    print(f"      → precio   : ${sell_result.avg_price:,.2f}")

    # ── Resumen ─────────────────────────────────────────────────
    print("\n" + "=" * 55)
    if sell_result.status != "failed":
        pnl = (sell_result.avg_price - buy_result.avg_price) * (sell_result.filled_amount or AMOUNT)
        print(f"[✓] CICLO COMPLETADO  |  P&L estimado: ${pnl:+.4f}")
    else:
        print("[!] El SELL falló — revisa la posición manualmente.")
    print("=" * 55)

if __name__ == "__main__":
    asyncio.run(test_testnet_trades())
