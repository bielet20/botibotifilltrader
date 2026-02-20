import asyncio
from typing import Dict, Any
from apps.engine.ema_cross import EMACrossStrategy
from apps.engine.technical_pro import TechnicalProStrategy
from apps.engine.algo_expert import AlgoExpertStrategy
from apps.engine.dynamic_reinvest import DynamicReinvestStrategy
from apps.engine.grid_trading import GridTradingStrategy
from apps.engine.market_data import MarketDataEngine
from apps.engine.paper_executor import PaperTradingExecutor
from apps.engine.paper_portfolio import PaperTradingPortfolio
from apps.engine.risk import RiskEngine
from apps.shared.database import SessionLocal
from apps.shared.models import BotDB, TradeDB, BotStatus, TradeSide, OrderLogDB, PositionDB

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
        elif "dynamic_reinvest" in strategy_name.lower():
            tp = config.get("take_profit_pct", 0.02)
            self.strategy = DynamicReinvestStrategy(take_profit_pct=tp)
        elif "grid_trading" in strategy_name.lower():
            upper = float(config.get("upper_limit", 70000))
            lower = float(config.get("lower_limit", 60000))
            grids = int(config.get("num_grids", 10))
            self.strategy = GridTradingStrategy(upper_limit=upper, lower_limit=lower, num_grids=grids)
        else:
            fast = config.get("fast_ema", 9)
            slow = config.get("slow_ema", 21)
            self.strategy = EMACrossStrategy(fast_ema=fast, slow_ema=slow)

        # Executor Factory — 'hyperliquid' for live trading, else paper
        executor_type = config.get("executor", "paper").lower()
        if executor_type == "hyperliquid":
            from apps.engine.hyperliquid_executor import HyperliquidExecutor
            self.executor = HyperliquidExecutor()
            self.mde = MarketDataEngine(exchange_id='hyperliquid')
            self.portfolio = None  # Live trading doesn't use a paper portfolio
            print(f"[BotManager] Bot {bot_id} using LIVE Hyperliquid executor ⚡")
        else:
            self.executor = PaperTradingExecutor(fee_rate=0.001)
            self.mde = MarketDataEngine()
            initial_balance = config.get("initial_balance", 10000.0)
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
                    'history': history,
                    'portfolio': self.portfolio.get_summary() if self.portfolio else {}
                })
                
                # 3. Validate with Risk Engine
                risk_result = await self.risk_engine.validate(signal)
                
                if risk_result.approved and signal.side != TradeSide.HOLD:
                    # 4. Execute (paper or live)
                    execution = await self.executor.execute(signal)

                    if execution.status != "failed":
                        executor_type = self.config.get("executor", "paper")
                        strategy_name = self.config.get("strategy", "ema_cross")
                        fee_amount = 0.0
                        pnl_amount = 0.0

                        if self.portfolio is not None:
                            # 5a. Paper Trading — update portfolio
                            portfolio_update = await self.portfolio.process_execution(
                                execution,
                                signal.side,
                                signal.symbol
                            )
                            if portfolio_update.get("success"):
                                fee_amount = portfolio_update.get("fee", 0.0)
                                pnl_amount = portfolio_update.get("pnl", 0.0)
                                with SessionLocal() as db:
                                    trade_entry = TradeDB(
                                        bot_id=self.bot_id,
                                        symbol=signal.symbol,
                                        side=signal.side,
                                        price=execution.avg_price,
                                        amount=execution.filled_amount,
                                        fee=fee_amount,
                                        pnl=pnl_amount,
                                        meta=signal.meta
                                    )
                                    db.add(trade_entry)
                                    db.commit()
                                print(f"[{self.bot_id}] Trade: {signal.side} {signal.symbol} | P&L: ${pnl_amount:.2f}")
                            else:
                                print(f"[{self.bot_id}] Trade rejected by portfolio: {portfolio_update.get('reason')}")
                        else:
                            # 5b. Live Hyperliquid
                            with SessionLocal() as db:
                                trade_entry = TradeDB(
                                    bot_id=self.bot_id,
                                    symbol=signal.symbol,
                                    side=signal.side,
                                    price=execution.avg_price,
                                    amount=execution.filled_amount,
                                    fee=0.0,
                                    pnl=0.0,
                                    meta={"order_id": execution.order_id, "status": execution.status}
                                )
                                db.add(trade_entry)
                                db.commit()
                            print(f"[{self.bot_id}] ⚡ LIVE: {signal.side} {signal.symbol} @ ${execution.avg_price:,.2f} | Order #{execution.order_id}")

                        # --- Persist to OrderLogDB (always, for audit) ---
                        with SessionLocal() as db:
                            order_log = OrderLogDB(
                                bot_id=self.bot_id,
                                symbol=signal.symbol,
                                side=signal.side,
                                status="closed",
                                price=execution.avg_price,
                                amount=signal.amount,
                                filled_amount=execution.filled_amount,
                                fee=fee_amount,
                                pnl=pnl_amount,
                                exchange_order_id=execution.order_id,
                                strategy=strategy_name,
                                executor=executor_type,
                                meta=signal.meta
                            )
                            db.add(order_log)

                            # --- Update PositionDB ---
                            existing_pos = db.query(PositionDB).filter(
                                PositionDB.bot_id == self.bot_id,
                                PositionDB.symbol == signal.symbol,
                                PositionDB.is_open == True
                            ).first()

                            if signal.side == TradeSide.BUY:
                                if existing_pos:
                                    # Average down the entry price
                                    total_qty = existing_pos.quantity + execution.filled_amount
                                    avg_price = (existing_pos.entry_price * existing_pos.quantity + execution.avg_price * execution.filled_amount) / total_qty
                                    existing_pos.entry_price = avg_price
                                    existing_pos.quantity = total_qty
                                    existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                                    existing_pos.current_price = execution.avg_price
                                else:
                                    new_pos = PositionDB(
                                        bot_id=self.bot_id,
                                        symbol=signal.symbol,
                                        side="long",
                                        entry_price=execution.avg_price,
                                        quantity=execution.filled_amount,
                                        current_price=execution.avg_price,
                                        fee_paid=fee_amount,
                                        is_open=True
                                    )
                                    db.add(new_pos)
                            elif signal.side == TradeSide.SELL and existing_pos:
                                # Reduce or close position
                                new_qty = existing_pos.quantity - execution.filled_amount
                                if new_qty <= 0.0001:
                                    existing_pos.is_open = False
                                    existing_pos.quantity = 0
                                else:
                                    existing_pos.quantity = new_qty
                                existing_pos.fee_paid = (existing_pos.fee_paid or 0) + fee_amount
                                existing_pos.current_price = execution.avg_price
                                existing_pos.unrealized_pnl = pnl_amount

                            db.commit()
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

        # Always update DB status, even if bot wasn't in active memory
        with SessionLocal() as db:
            bot_entry = db.query(BotDB).filter(BotDB.id == bot_id).first()
            if bot_entry:
                bot_entry.status = "stopped"
                db.commit()
                return True

        return bool(bot)  # Return True only if was in memory but not in DB

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
        print("[BotManager] Resuming active bots from database...")
        with SessionLocal() as db:
            active_db_bots = db.query(BotDB).filter(BotDB.status == "running", BotDB.is_archived == False).all()
            if not active_db_bots:
                print("[BotManager] No bots to resume.")
                return
            for db_bot in active_db_bots:
                if db_bot.id not in self.active_bots:
                    print(f"[BotManager] Resuming bot: {db_bot.id} (strategy={db_bot.strategy})")
                    self.start_bot(db_bot.id, db_bot.config)
                else:
                    print(f"[BotManager] Bot {db_bot.id} already in memory — skipping.")
        print(f"[BotManager] {len(self.active_bots)} bot(s) running.")

if __name__ == "__main__":
    async def main():
        print("Bot Manager Worker started. Standby mode.")
        while True:
            await asyncio.sleep(3600)
            
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
