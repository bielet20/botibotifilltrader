import asyncio
from typing import Dict, Any
from apps.engine.ema_cross import EMACrossStrategy
from apps.engine.technical_pro import TechnicalProStrategy
from apps.engine.algo_expert import AlgoExpertStrategy
from apps.engine.market_data import MarketDataEngine
from apps.engine.paper_executor import PaperTradingExecutor
from apps.engine.paper_portfolio import PaperTradingPortfolio
from apps.engine.risk import RiskEngine
from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, BotStatus, TradeSide

class BotInstance:
    def __init__(self, bot_id: str, config: Dict):
        self.bot_id = bot_id
        self.config = config
        self.status = BotStatus.STOPPED
        self._task = None
        
        # Strategy Factory
        strategy_name = config.get("strategy", "ema_cross")
        if "technical_pro" in strategy_name.lower():
            self.strategy = TechnicalProStrategy()
        elif "algo_expert" in strategy_name.lower():
            self.strategy = AlgoExpertStrategy()
        else:
            fast = config.get("fast_ema", 9)
            slow = config.get("slow_ema", 21)
            self.strategy = EMACrossStrategy(fast_ema=fast, slow_ema=slow)
            
        self.mde = MarketDataEngine()
        
        # Paper Trading Components
        initial_balance = config.get("initial_balance", 10000.0)
        self.executor = PaperTradingExecutor(fee_rate=0.001)
        self.portfolio = PaperTradingPortfolio(bot_id, initial_balance=initial_balance)
        self.risk_engine = RiskEngine()

    async def run(self):
        self.status = BotStatus.RUNNING
        
        # Sync initial state to DB
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == self.bot_id).first()
            if not bot_entry:
                bot_entry = BotDB(id=self.bot_id, strategy=self.config.get("strategy"), status="running", config=self.config)
                db.add(bot_entry)
            else:
                bot_entry.status = "running"
            db.commit()

        print(f"Bot {self.bot_id} starting loop...")
        try:
            while self.status == BotStatus.RUNNING:
                symbol = self.config.get("symbol", "BTC/USDT")
                # 1. Fetch data
                ticker = await self.mde.fetch_ticker(symbol)
                last_price = ticker.get('last', 0.0)
                
                # Fetch history for technical analysis if needed
                history = await self.mde.fetch_ohlcv(symbol, limit=250)
                
                # 2. Analyze
                signal = await self.strategy.analyze({
                    'last_price': last_price, 
                    'symbol': symbol,
                    'history': history
                })
                
                # 3. Validate with Risk Engine
                risk_result = await self.risk_engine.validate(signal)
                
                if risk_result.approved and signal.side != TradeSide.HOLD:
                    # 4. Execute with Paper Trading Executor
                    execution = await self.executor.execute(signal)
                    
                    # 5. Update Portfolio
                    portfolio_update = await self.portfolio.process_execution(
                        execution, 
                        signal.side, 
                        signal.symbol
                    )
                    
                    if portfolio_update.get("success"):
                        # 6. Save to DB with P&L
                        with SessionLocal() as db:
                            trade_entry = TradeDB(
                                bot_id=self.bot_id,
                                symbol=signal.symbol,
                                side=signal.side,
                                price=execution.avg_price,
                                amount=execution.filled_amount,
                                fee=portfolio_update.get("fee", 0.0),
                                pnl=portfolio_update.get("pnl", 0.0),
                                meta=signal.meta
                            )
                            db.add(trade_entry)
                            db.commit()
                        print(f"[{self.bot_id}] Trade executed: {signal.side} {signal.symbol} | P&L: ${portfolio_update.get('pnl', 0):.2f}")
                    else:
                        print(f"[{self.bot_id}] Trade rejected by portfolio: {portfolio_update.get('reason')}")
                elif not risk_result.approved:
                    print(f"[{self.bot_id}] Trade rejected by risk engine: {risk_result.reason}")
                else:
                    print(f"[{self.bot_id}] Holding position...")
                    
                await asyncio.sleep(10)
        except Exception as e:
            print(f"Bot {self.bot_id} failed: {e}")
        finally:
            self.status = BotStatus.STOPPED
            with SessionLocal() as db:
                bot_entry = db.query(BotDB).filter(BotDB.id == self.bot_id).first()
                if bot_entry:
                    bot_entry.status = "stopped"
                    db.commit()
            print(f"Bot {self.bot_id} loop ended.")

class BotManager:
    def __init__(self):
        self.active_bots: Dict[str, BotInstance] = {}

    def start_bot(self, bot_id: str, config: Dict):
        if bot_id in self.active_bots:
            return False
        
        bot = BotInstance(bot_id, config)
        self.active_bots[bot_id] = bot
        bot._task = asyncio.create_task(bot.run())
        return True

    def stop_bot(self, bot_id: str):
        bot = self.active_bots.get(bot_id)
        if bot:
            bot.status = BotStatus.STOPPED
            if bot._task:
                bot._task.cancel()
            del self.active_bots[bot_id]
            return True
        return False

    def delete_bot(self, bot_id: str):
        # 1. Stop if running
        self.stop_bot(bot_id)
        # 2. Delete from DB
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                db.delete(bot_entry)
                db.commit()
                return True
        return False

    def archive_bot(self, bot_id: str):
        # 1. Stop if running
        self.stop_bot(bot_id)
        # 2. Mark as archived in DB
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.is_archived = True
                db.commit()
                return True
        return False

    def restore_bot(self, bot_id: str):
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.is_archived = False
                db.commit()
                return True
        return False

    async def resume_bots(self):
        print("Resuming active bots from database...")
        with SessionLocal() as db:
            active_db_bots = db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all()
            for db_bot in active_db_bots:
                print(f"Resuming bot {db_bot.id}...")
                self.start_bot(db_bot.id, db_bot.config)

if __name__ == "__main__":
    async def main():
        print("Bot Manager Worker started. Standby mode.")
        while True:
            await asyncio.sleep(3600)
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
