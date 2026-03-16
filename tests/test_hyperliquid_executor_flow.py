import pytest
from unittest.mock import AsyncMock

from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.shared.models import TradeSignal, TradeSide


class FakeExchange:
    def __init__(self):
        self.markets = {}
        self.walletAddress = "0xabc"
        self.positions = []
        self.created_orders = []

    async def load_markets(self):
        self.markets = {"BTC/USDC:USDC": {}}

    async def fetch_positions(self, params=None):
        return list(self.positions)

    async def fetch_ticker(self, symbol):
        return {"last": 100000.0}

    async def create_order(self, symbol, type, side, amount, price=None, params=None):
        order = {
            "id": f"ord-{len(self.created_orders) + 1}",
            "status": "closed",
            "filled": amount,
            "amount": amount,
            "average": price or 100000.0,
            "price": price or 100000.0,
            "params": params or {},
            "symbol": symbol,
            "side": side,
            "type": type,
        }
        self.created_orders.append(order)
        return order


def build_executor(fake_exchange: FakeExchange) -> HyperliquidExecutor:
    executor = HyperliquidExecutor.__new__(HyperliquidExecutor)
    executor.exchange = fake_exchange
    executor.is_configured = True
    return executor


def test_extract_side_qty_supports_explicit_short_with_positive_contracts():
    pos = {
        "side": "short",
        "contracts": 0.02,
        "info": {
            "position": {"szi": "-0.02"},
        },
    }

    side, qty = HyperliquidExecutor._extract_side_qty(pos)

    assert side == "short"
    assert qty == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_execute_reduce_only_caps_amount_and_sets_ioc():
    exchange = FakeExchange()
    executor = build_executor(exchange)
    executor._fetch_symbol_position = AsyncMock(return_value=("short", 0.02))
    executor._place_stop_loss = AsyncMock()

    signal = TradeSignal(
        symbol="BTC/USDC:USDC",
        side=TradeSide.BUY,
        amount=0.05,
        strategy_id="test",
        meta={"reduce_only": True},
    )

    result = await executor.execute(signal)

    assert result.status == "closed"
    assert len(exchange.created_orders) == 1
    order = exchange.created_orders[0]
    assert order["side"] == "buy"
    assert order["amount"] == pytest.approx(0.02)
    assert order["params"].get("reduceOnly") is True
    assert order["params"].get("timeInForce") == "Ioc"
    executor._place_stop_loss.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_reduce_only_skips_when_no_position():
    exchange = FakeExchange()
    executor = build_executor(exchange)
    executor._fetch_symbol_position = AsyncMock(return_value=("", 0.0))
    executor._place_stop_loss = AsyncMock()

    signal = TradeSignal(
        symbol="BTC/USDC:USDC",
        side=TradeSide.SELL,
        amount=0.01,
        strategy_id="test",
        meta={"reduce_only": True},
    )

    result = await executor.execute(signal)

    assert result.order_id == "no_position"
    assert result.status == "failed"
    assert len(exchange.created_orders) == 0
    executor._place_stop_loss.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_open_buy_places_stop_loss():
    exchange = FakeExchange()
    executor = build_executor(exchange)
    executor._place_stop_loss = AsyncMock()

    signal = TradeSignal(
        symbol="BTC/USDC:USDC",
        side=TradeSide.BUY,
        amount=0.01,
        strategy_id="test",
    )

    result = await executor.execute(signal)

    assert result.status == "closed"
    assert len(exchange.created_orders) == 1
    order = exchange.created_orders[0]
    assert order["side"] == "buy"
    assert order["params"] == {}
    executor._place_stop_loss.assert_awaited_once()
