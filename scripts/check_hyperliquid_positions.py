#!/usr/bin/env python3
"""
Script para verificar las posiciones reales en Hyperliquid Mainnet
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
import ccxt
import json

# Load environment variables
load_dotenv()

def check_positions():
    """Check all positions on Hyperliquid Mainnet"""
    print("🔍 Verificando posiciones en Hyperliquid MAINNET...\n")
    
    # Get credentials
    wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
    signing_key = os.getenv("HYPERLIQUID_SIGNING_KEY")
    
    if not all([wallet_address, signing_key]):
        print("❌ ERROR: Faltan credenciales de Hyperliquid en .env")
        print(f"   HYPERLIQUID_WALLET_ADDRESS: {'✅' if wallet_address else '❌'}")
        print(f"   HYPERLIQUID_SIGNING_KEY: {'✅' if signing_key else '❌'}")
        return
    
    print(f"✅ Wallet Address: {wallet_address[:10]}...{wallet_address[-8:]}\n")
    
    try:
        # Initialize exchange (MAINNET)
        exchange = ccxt.hyperliquid({
            'walletAddress': wallet_address,
            'privateKey': signing_key,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'network': 'mainnet'  # IMPORTANT: mainnet
            }
        })
        
        # Fetch open positions
        print("📊 Obteniendo posiciones abiertas...\n")
        positions = exchange.fetch_positions()
        
        if not positions:
            print("⚠️  No se encontraron posiciones abiertas en Hyperliquid MAINNET")
            return
        
        # Filter only open positions
        open_positions = [p for p in positions if float(p.get('contracts', 0)) != 0]
        
        if not open_positions:
            print("⚠️  No hay posiciones con contratos activos")
            return
        
        print(f"✅ Se encontraron {len(open_positions)} posición(es) abierta(s):\n")
        print("═" * 120)
        
        for idx, pos in enumerate(open_positions, 1):
            symbol = pos.get('symbol', 'N/A')
            side = pos.get('side', 'N/A')
            contracts = float(pos.get('contracts', 0) or 0)
            entry_price = float(pos.get('entryPrice', 0) or 0)
            mark_price = float(pos.get('markPrice', 0) or 0)
            unrealized_pnl = float(pos.get('unrealizedPnl', 0) or 0)
            leverage = pos.get('leverage', 1) or 1
            notional = float(pos.get('notional', 0) or 0)
            
            print(f"Posición #{idx}:")
            print(f"  Symbol:          {symbol}")
            print(f"  Side:            {side.upper()}")
            print(f"  Leverage:        {leverage}x")
            print(f"  Contracts:       {contracts}")
            print(f"  Entry Price:     ${entry_price:,.2f}")
            print(f"  Mark Price:      ${mark_price:,.2f}")
            print(f"  Notional:        ${notional:,.2f}")
            print(f"  Unrealized PnL:  ${unrealized_pnl:,.4f}")
            if entry_price > 0 and mark_price > 0:
                print(f"  % Change:        {((mark_price - entry_price) / entry_price * 100):.2f}%")
            else:
                print(f"  % Change:        N/A")
            print("─" * 120)
        
        # Show raw data for debugging
        print("\n🔧 Datos RAW (para debug):")
        print(json.dumps(open_positions, indent=2, default=str))
        
    except Exception as e:
        print(f"❌ ERROR al consultar Hyperliquid: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_positions()
