import os
import requests

def get_env_variable(var_name):
    """Get the environment variable or return exception."""
    try:
        return os.environ[var_name]
    except KeyError:
        raise EnvironmentError(f"Set the {var_name} environment variable.")

def check_balance():
    """Check the wallet balance on Hyperliquid Testnet."""
    wallet_address = get_env_variable("WALLET_ADDRESS")
    api_url = f"https://testnet.hyperliquid.com/api/v1/balance/{wallet_address}"

    response = requests.get(api_url)
    if response.status_code == 200:
        balance = response.json().get("balance", 0)
        print(f"Wallet Balance: {balance} ETH")
        return balance
    else:
        print("Failed to fetch balance. Check wallet address or API connectivity.")
        return None

def execute_test_trade():
    """Execute a test trade on Hyperliquid Testnet."""
    wallet_address = get_env_variable("WALLET_ADDRESS")
    signing_key = get_env_variable("SIGNING_KEY")
    api_url = "https://testnet.hyperliquid.com/api/v1/trade"

    trade_payload = {
        "wallet": wallet_address,
        "key": signing_key,
        "action": "buy",
        "amount": 0.001,  # Example trade amount
        "symbol": "ETH-USD"
    }

    response = requests.post(api_url, json=trade_payload)
    if response.status_code == 200:
        print("Trade executed successfully:", response.json())
    else:
        print("Trade execution failed:", response.text)

if __name__ == "__main__":
    print("Starting balance check and test trade...")
    balance = check_balance()
    if balance and balance > 0.001:
        execute_test_trade()
    else:
        print("Insufficient balance to execute trade.")