import asyncio
import httpx
from apps.shared.database import SessionLocal
from apps.shared.models import PositionDB, BotDB
import uuid
from datetime import datetime

async def verify():
    print("--- [Verification] Simulating External Position ---")
    
    # 1. Manually insert an 'ORPHAN' position into the database
    # This simulates a position found on the exchange that we don't know about yet
    symbol = "ETH/USDT"
    with SessionLocal() as db:
        # Clean up previous tests
        db.query(PositionDB).filter(PositionDB.symbol == symbol).delete()
        db.commit()
        
        orphan_pos = PositionDB(
            bot_id="ORPHAN",
            symbol=symbol,
            side="long",
            entry_price=2500.0,
            quantity=1.0,
            current_price=2550.0,
            unrealized_pnl=50.0,
            is_open=True
        )
        db.add(orphan_pos)
        db.commit()
    
    print(f"Created orphan position for {symbol}")

    # 2. Trigger Sync via API (simulated here by calling the service directly or via localhost if server is up)
    # Since the server is running in the background from previous steps, we can use httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("http://127.0.0.1:8000/api/sync/positions")
            print(f"Sync Result: {response.json()}")
            
            # 3. Adopt the position
            bot_id = f"AdoptedBot_{uuid.uuid4().hex[:4]}"
            adopt_response = await client.post(f"http://127.0.0.1:8000/api/bots/adopt?bot_id={bot_id}&symbol={symbol}")
            print(f"Adopt Result: {adopt_response.json()}")
            
            # 4. Verify in DB
            with SessionLocal() as db:
                pos = db.query(PositionDB).filter(PositionDB.bot_id == bot_id).first()
                if pos:
                    print(f"SUCCESS: Position for {symbol} is now managed by {bot_id}")
                else:
                    print("FAILURE: Position was not adopted correctly")
        except Exception as e:
            print(f"Error during API verification: {e}")

if __name__ == "__main__":
    asyncio.run(verify())
