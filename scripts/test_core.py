import asyncio
from apps.engine.market_data import MarketDataEngine
from apps.engine.risk import RiskEngine
from apps.shared.models import TradeSignal, TradeSide
import ccxt.async_support as ccxt

async def test_connectivity():
    print("--- [1] Testing Market Data Engine (CCXT Public) ---")
    mde = MarketDataEngine('binance')
    price = await mde.get_latest_price('BTC/USDT')
    print(f"Latest BTC/Price on Binance (Public): {price}")

    print("\n--- [2] Testing Risk Engine Logic ---")
    risk = RiskEngine(global_kill_switch=False, max_exposure=100)
    
    # Signal within limits
    signal_ok = TradeSignal(symbol='BTC/USDT', side=TradeSide.BUY, amount=0.001, price=40000, strategy_id='test_strat')
    res_ok = await risk.validate(signal_ok)
    print(f"Risk Check (OK): Approved={res_ok.approved}, Reason='{res_ok.reason}'")

    # Signal over limit
    signal_fail = TradeSignal(symbol='BTC/USDT', side=TradeSide.BUY, amount=10, price=40000, strategy_id='test_strat')
    res_fail = await risk.validate(signal_fail)
    print(f"Risk Check (OVER LIMIT): Approved={res_fail.approved}, Reason='{res_fail.reason}'")

    # Kill switch
    risk.trigger_kill_switch()
    res_kill = await risk.validate(signal_ok)
    print(f"Risk Check (KILL SWITCH): Approved={res_kill.approved}, Reason='{res_kill.reason}'")

if __name__ == "__main__":
    asyncio.run(test_connectivity())
