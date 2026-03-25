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

        # If exchange query failed, keep local state untouched to avoid false closures.
        if exchange_positions is None:
            results["sync_skipped"] = True
            results["reason"] = "exchange_fetch_failed"
            return results

        with SessionLocal() as db:
            # 1. Obtener todas las posiciones abiertas en DB local
            local_positions = db.query(PositionDB).filter(PositionDB.is_open == True).all()
            local_pos_map = {f"{p.bot_id}_{p.symbol}": p for p in local_positions}
            
            # 2. Procesar posiciones del exchange
            exchange_processed_keys = set()
            
            for ex_pos in exchange_positions:
                symbol = ex_pos['symbol']
                position_leverage = int(ex_pos.get('leverage', 1.0))
                
                # Smart matching: priorizar coincidencia de symbol + leverage + status
                all_bots = db.query(BotDB).all()
                managing_bot = None
                
                # Priority 1: Running bot with matching symbol AND leverage
                for b in all_bots:
                    if (b.config and 
                        b.config.get('symbol') == symbol and 
                        b.status == 'running' and
                        int(b.config.get('leverage', 1)) == position_leverage):
                        managing_bot = b
                        break
                
                # Priority 2: Running bot with matching symbol (any leverage)
                if not managing_bot:
                    for b in all_bots:
                        if (b.config and 
                            b.config.get('symbol') == symbol and 
                            b.status == 'running'):
                            managing_bot = b
                            break
                
                # Priority 3: Any bot with matching symbol + leverage
                if not managing_bot:
                    for b in all_bots:
                        if (b.config and 
                            b.config.get('symbol') == symbol and
                            int(b.config.get('leverage', 1)) == position_leverage):
                            managing_bot = b
                            break
                
                # Priority 4: Any bot with matching symbol
                if not managing_bot:
                    for b in all_bots:
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
                    pos.leverage = ex_pos.get('leverage', 1.0)
                    pos.updated_at = datetime.utcnow()
                    results["synchronized"] += 1
                else:
                    # Check if position exists with different bot_id (needs reassignment)
                    existing_pos = None
                    for p in local_positions:
                        if p.symbol == symbol and p.is_open:
                            existing_pos = p
                            break
                    
                    if existing_pos and bot_id != "ORPHAN":
                        # Regla de seguridad (producción):
                        # No reasignar una posición ya asociada a un bot específico salvo que sea claramente huérfana
                        # o que el bot original ya no exista/esté archivado. Esto evita "robar" posiciones entre bots
                        # parados, algo peligroso en live.
                        old_bot_id = str(existing_pos.bot_id or "").strip()
                        old_bot = db.query(BotDB).filter(BotDB.id == old_bot_id).first() if old_bot_id else None
                        old_is_orphan = (old_bot_id == "ORPHAN")
                        old_missing_or_archived = (old_bot is None) or bool(getattr(old_bot, "is_archived", False))

                        if old_is_orphan or old_missing_or_archived:
                            existing_pos.bot_id = bot_id
                            if not existing_pos.meta:
                                existing_pos.meta = {}
                            existing_pos.meta['reassigned_from'] = old_bot_id or "UNKNOWN"
                            existing_pos.meta['reassigned_at'] = datetime.utcnow().isoformat()
                            print(f"[PositionSync] Reassigned position {symbol} from {old_bot_id} to {bot_id}")

                        # Siempre actualizamos el mark/pnl/cantidad aunque NO reasignemos.
                        existing_pos.current_price = ex_pos['current_price']
                        existing_pos.unrealized_pnl = ex_pos['unrealized_pnl']
                        existing_pos.quantity = ex_pos['quantity']
                        existing_pos.leverage = ex_pos.get('leverage', 1.0)
                        existing_pos.updated_at = datetime.utcnow()
                        results["synchronized"] += 1
                    elif existing_pos and bot_id == "ORPHAN":
                        # Position exists but no matching bot found
                        existing_pos.current_price = ex_pos['current_price']
                        existing_pos.unrealized_pnl = ex_pos['unrealized_pnl']
                        existing_pos.quantity = ex_pos['quantity']
                        existing_pos.leverage = ex_pos.get('leverage', 1.0)
                        existing_pos.updated_at = datetime.utcnow()
                        results["orphans"].append(ex_pos)
                        results["synchronized"] += 1
                    else:
                        # Nueva posición detectada
                        if bot_id == "ORPHAN":
                            # Persist orphan positions so they are visible and controllable from the app.
                            new_pos = PositionDB(
                                bot_id="ORPHAN",
                                symbol=symbol,
                                side=ex_pos['side'],
                                entry_price=ex_pos['entry_price'],
                                quantity=ex_pos['quantity'],
                                leverage=ex_pos.get('leverage', 1.0),
                                current_price=ex_pos['current_price'],
                                unrealized_pnl=ex_pos['unrealized_pnl'],
                                is_open=True,
                                meta={"source": "sync_orphan_discovery"}
                            )
                            db.add(new_pos)
                            results["orphans"].append(ex_pos)
                            results["synchronized"] += 1
                        else:
                            new_pos = PositionDB(
                                bot_id=bot_id,
                                symbol=symbol,
                                side=ex_pos['side'],
                                entry_price=ex_pos['entry_price'],
                                quantity=ex_pos['quantity'],
                                leverage=ex_pos.get('leverage', 1.0),
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
