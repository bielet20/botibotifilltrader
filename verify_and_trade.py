import os
import json
import asyncio
import urllib.request

from apps.engine.hyperliquid_executor import HyperliquidExecutor
from apps.shared.models import TradeSignal, TradeSide

def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_env_variable(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise EnvironmentError(f"Set one of these environment variables: {', '.join(names)}")


def _public_account_value(wallet: str, use_testnet: bool) -> float:
    base_url = "https://api.hyperliquid-testnet.xyz" if use_testnet else "https://api.hyperliquid.xyz"
    payload = json.dumps({"type": "clearinghouseState", "user": wallet}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/info",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    margin = data.get("marginSummary") or {}
    return float(margin.get("accountValue") or 0.0)

def check_balance() -> float:
    wallet_address = _get_env_variable("HYPERLIQUID_WALLET_ADDRESS", "WALLET_ADDRESS")
    use_testnet = _bool_env("HYPERLIQUID_USE_TESTNET", True)
    balance = _public_account_value(wallet_address, use_testnet)
    env_name = "TESTNET" if use_testnet else "MAINNET"
    print(f"Wallet Balance ({env_name}): {balance} USDC")
    return balance


async def execute_test_trade(amount: float = 0.001, symbol: str = "ETH/USDC:USDC") -> None:
    wallet_address = _get_env_variable("HYPERLIQUID_WALLET_ADDRESS", "WALLET_ADDRESS")
    signing_key = _get_env_variable("HYPERLIQUID_SIGNING_KEY", "SIGNING_KEY")
    use_testnet = _bool_env("HYPERLIQUID_USE_TESTNET", True)

    if not use_testnet and not _bool_env("HYPERLIQUID_ALLOW_MAINNET_TRADE", False):
        print("Mainnet deshabilitada por seguridad. Define HYPERLIQUID_ALLOW_MAINNET_TRADE=true para confirmar.")
        return

    if not HyperliquidExecutor._is_valid_wallet(wallet_address):
        raise RuntimeError("Wallet inválida o ausente")
    if not HyperliquidExecutor._is_valid_private_key(signing_key):
        raise RuntimeError("Signing key inválida o ausente")

    executor = HyperliquidExecutor(use_testnet=use_testnet)
    if not executor.is_configured:
        raise RuntimeError("Credenciales Hyperliquid no configuradas")

    env_name = "TESTNET" if use_testnet else "MAINNET"
    print(f"[{env_name}] BUY {amount} {symbol}")
    try:
        signal = TradeSignal(
            strategy_id="VERIFY_AND_TRADE",
            symbol=symbol,
            side=TradeSide.BUY,
            amount=amount,
            price=None,
            meta={"source": "verify_and_trade"},
        )
        result = await executor.execute(signal)
        if result.status == "failed":
            print("Trade execution failed")
        else:
            print("Trade executed successfully:", result)
    finally:
        await executor.close()

if __name__ == "__main__":
    print("Starting balance check and test trade...")
    balance = check_balance()
    if balance and balance > 0.001:
        asyncio.run(execute_test_trade())
    else:
        print("Insufficient balance to execute trade.")