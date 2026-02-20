"""
Test de trades en MAINNET de Hyperliquid.
⚠️ ESTO USA FONDOS REALES. Montos mínimos, solo para verificar la conexión.
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

# ── Configuración conservadora para 15 USDC ────────────────────
# BTC mínimo en Hyperliquid es 0.001 BTC (~$67 notional)
# Con 5x leverage → ~13.5 USDC de margen requerido ✓
SYMBOL = "BTC/USDC:USDC"
AMOUNT = 0.001   # Mínimo BTC, ~$67 notional / 5x = ~$13.5 margen

async def test_mainnet_trades():
    print("=" * 55)
    print("  ⚠️  HYPERLIQUID MAINNET — FONDOS REALES ⚠️")
    print("=" * 55)

    wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
    testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "False").lower() == "true"

    print(f"  Wallet : {wallet}")
    print(f"  Red    : {'TESTNET' if testnet else 'MAINNET ⚠️'}")
    print(f"  Par    : {SYMBOL}  |  Qty: {AMOUNT} BTC (mínimo)")
    print()

    # ── Verificar balance real antes de operar ──────────────────
    key = os.getenv("HYPERLIQUID_SIGNING_KEY")
    exch = ccxt.hyperliquid({'privateKey': key, 'walletAddress': wallet})

    try:
        balance = await exch.fetch_balance()
        usdc = balance.get('USDC', {}).get('total', 0) or balance.get('total', {}).get('USDC', 0)
        print(f"[INFO] Balance Mainnet: {usdc:.2f} USDC")

        if usdc < 10:
            print(f"[✗] Balance insuficiente ({usdc:.2f} USDC). Necesitas al menos ~13 USDC para este trade.")
            await exch.close()
            return
    except Exception as e:
        print(f"[WARN] No se pudo leer el balance: {e}")
    finally:
        await exch.close()

    # ── Ver precio y estimar margen ─────────────────────────────
    executor = HyperliquidExecutor()
    ticker = await executor.exchange.fetch_ticker(SYMBOL)
    price = ticker['last']
    notional = price * AMOUNT
    margin_est = notional / 5  # Asumiendo 5x leverage
    print(f"[INFO] Precio BTC: ${price:,.2f}")
    print(f"[INFO] Notional:   ${notional:,.2f}  |  Margen estimado (5x): ${margin_est:.2f} USDC")
    await executor.exchange.close()

    print()
    print("[1/2] Enviando orden BUY en MAINNET …")

    executor2 = HyperliquidExecutor()
    ticker2 = await executor2.exchange.fetch_ticker(SYMBOL)
    price2 = ticker2['last']

    buy_signal = TradeSignal(
        symbol=SYMBOL,
        side=TradeSide.BUY,
        amount=AMOUNT,
        price=price2,
        strategy_id="mainnet_live_test"
    )

    buy_result = await executor2.execute(buy_signal)
    print(f"      → orden_id : {buy_result.order_id}")
    print(f"      → estado   : {buy_result.status}")
    print(f"      → precio   : ${buy_result.avg_price:,.2f}")
    print(f"      → cantidad : {buy_result.filled_amount}")

    if buy_result.status == "failed":
        print("\n[✗] El BUY falló. Revisa que tengas suficiente balance o que el margen sea válido.")
        return

    print(f"\n✅ BUY ejecutado en Mainnet. Esperando 2s antes del SELL …")
    await asyncio.sleep(2)

    # ── SELL para cerrar posición ───────────────────────────────
    print("\n[2/2] Enviando orden SELL (cerrar posición) …")
    executor3 = HyperliquidExecutor()
    ticker3 = await executor3.exchange.fetch_ticker(SYMBOL)
    price3 = ticker3['last']

    sell_signal = TradeSignal(
        symbol=SYMBOL,
        side=TradeSide.SELL,
        amount=buy_result.filled_amount or AMOUNT,
        price=price3,
        strategy_id="mainnet_live_test"
    )

    sell_result = await executor3.execute(sell_signal)
    print(f"      → orden_id : {sell_result.order_id}")
    print(f"      → estado   : {sell_result.status}")
    print(f"      → precio   : ${sell_result.avg_price:,.2f}")

    # ── Resumen ─────────────────────────────────────────────────
    print("\n" + "=" * 55)
    if sell_result.status != "failed":
        pnl = (sell_result.avg_price - buy_result.avg_price) * (buy_result.filled_amount or AMOUNT)
        print(f"[✓] CICLO COMPLETADO | P&L real: ${pnl:+.4f} USDC")
        print(f"    POSICIÓN CERRADA — fondos de vuelta en la cuenta.")
    else:
        print("[!] El SELL falló. Posición abierta — ciérrala manualmente en la app.")
    print("=" * 55)

if __name__ == "__main__":
    asyncio.run(test_mainnet_trades())
