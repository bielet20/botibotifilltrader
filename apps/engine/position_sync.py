from typing import List, Dict, Any
from apps.shared.database import SessionLocal
from apps.shared.models import PositionDB, BotDB
from apps.shared.interfaces import BaseExecutionProvider
import uuid
from datetime import datetime

class PositionSyncService:
    def __init__(self, executor: BaseExecutionProvider):
        self.executor = executor

    async def sync_positions(self) -> Dict[str, Any]:
        """
        Sincroniza las posiciones del exchange con la base de datos local.
        Identifica posiciones 'huérfanas' (sin bot asociado).
        """
        exchange_positions = await self.executor.fetch_active_positions()
        
        results = {
            "synchronized": 0,
            "orphans": [],
            "closed_locally": 0
        }

        with SessionLocal() as db:
            # 1. Obtener todas las posiciones abiertas en DB local
            local_positions = db.query(PositionDB).filter(PositionDB.is_open == True).all()
            local_pos_map = {f"{p.bot_id}_{p.symbol}": p for p in local_positions}
            
            # 2. Procesar posiciones del exchange
            exchange_processed_keys = set()
            
            for ex_pos in exchange_positions:
                symbol = ex_pos['symbol']
                # Intentamos encontrar un bot que ya esté gestionando este símbolo
                # (Simplificación: buscamos bots con este símbolo en su config)
                bot = db.query(BotDB).filter(BotDB.status == 'running').all()
                managing_bot = None
                for b in bot:
                    if b.config and b.config.get('symbol') == symbol:
                        managing_bot = b
                        break
                
                bot_id = managing_bot.id if managing_bot else "ORPHAN"
                key = f"{bot_id}_{symbol}"
                exchange_processed_keys.add(key)
                
                if key in local_pos_map:
                    # Actualizar posición existente
                    pos = local_pos_map[key]
                    pos.current_price = ex_pos['current_price']
                    pos.unrealized_pnl = ex_pos['unrealized_pnl']
                    pos.quantity = ex_pos['quantity']
                    pos.updated_at = datetime.utcnow()
                    results["synchronized"] += 1
                else:
                    # Nueva posición detectada (o huérfana)
                    if bot_id == "ORPHAN":
                        results["orphans"].append(ex_pos)
                    else:
                        new_pos = PositionDB(
                            bot_id=bot_id,
                            symbol=symbol,
                            side=ex_pos['side'],
                            entry_price=ex_pos['entry_price'],
                            quantity=ex_pos['quantity'],
                            current_price=ex_pos['current_price'],
                            unrealized_pnl=ex_pos['unrealized_pnl'],
                            is_open=True,
                            meta={"source": "sync_discovery"}
                        )
                        db.add(new_pos)
                        results["synchronized"] += 1
            
            # 3. Marcar como cerradas las posiciones locales que ya no existen en el exchange
            for key, pos in local_pos_map.items():
                if key not in exchange_processed_keys:
                    pos.is_open = False
                    pos.updated_at = datetime.utcnow()
                    results["closed_locally"] += 1
            
            db.commit()
            
        return results
