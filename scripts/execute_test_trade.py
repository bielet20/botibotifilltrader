import asyncio
import os
import sys
from dotenv import load_dotenv

# Añadir el root al path para poder importar las apps
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.shared.models import TradeSignal, TradeSide

async def test_order():
    load_dotenv()
    print("--- Iniciando Prueba de Conectividad Hyperliquid ---")
    
    # Usar configuración de .env
    use_testnet = os.getenv("HYPERLIQUID_USE_TESTNET", "True").lower() == "true"
    executor = HyperliquidExecutor() # Usará .env
    
    print(f"Modo Testnet: {use_testnet}")
    
    if not executor.is_configured:
        print("❌ Error: Credenciales de Hyperliquid no configuradas en .env")
        return

    try:
        print("Cargando mercados y verificando balance...")
        await executor.exchange.load_markets()
        
        # Verificar balance de USDC
        balance = await executor.exchange.fetch_balance()
        usdc_balance = balance.get('USDC', {}).get('free', 0)
        print(f"Balance de USDC disponible: ${usdc_balance:,.2f}")
        
        if usdc_balance < 1:
            print("⚠️ Advertencia: Balance muy bajo o inexistente. Es posible que la orden falle.")

        # Creamos una señal de prueba: Compra de 0.0002 BTC (~$13.50-14.00, superando el mínimo de $10)
        signal = TradeSignal(
            strategy_id="TEST-STRATEGY",
            symbol="BTC/USDT",
            side=TradeSide.BUY,
            amount=0.0002,
            price=None
        )
        
        print(f"Enviando orden de prueba: {signal.side} {signal.amount} {signal.symbol}...")
        result = await executor.execute(signal)
        
        if result.status != "failed":
            print(f"✅ ¡Éxito! Orden ejecutada. ID: {result.order_id}")
            print(f"Estado final: {result.status}")
        else:
            print(f"❌ Fallo en la ejecución. Revisa los logs.")
    except Exception as e:
        print(f"❌ Error inesperado: {str(e)}")
    finally:
        await executor.exchange.close()

if __name__ == "__main__":
    asyncio.run(test_order())
