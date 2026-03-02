import ccxt.async_support as ccxt
import asyncio
import os
from dotenv import load_dotenv

async def verify():
    load_dotenv()
    wallet = os.getenv('HYPERLIQUID_WALLET_ADDRESS')
    key = os.getenv('HYPERLIQUID_SIGNING_KEY')
    print(f'Wallet: {wallet}')
    
    exchange = ccxt.hyperliquid({
        'privateKey': key,
        'walletAddress': wallet,
    })
    exchange.set_sandbox_mode(True)
    
    try:
        balance = await exchange.fetch_balance()
        usdc = balance.get('USDC', {}).get('total', 0)
        print(f'STATUS: {"OK" if usdc > 0 else "NO_FUNDS"}')
        print(f'Balance: {usdc}')
    except Exception as e:
        print(f'STATUS: ERROR - {e}')
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(verify())
