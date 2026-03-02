from apps.shared.interfaces import BaseRiskProvider
from apps.shared.models import TradeSignal, RiskResult

class RiskEngine(BaseRiskProvider):
    def __init__(self, global_kill_switch: bool = False, max_exposure: float = 1000000):
        self.kill_switch = global_kill_switch
        self.max_exposure = max_exposure

    async def validate(self, signal: TradeSignal, context: dict = {}) -> RiskResult:
        """
        Valida que una señal no exceda los límites de riesgo.
        Si detecta una situación crítica (ej. drawdown excesivo), 
        puede forzar una salida de emergencia.
        """
        if self.kill_switch:
            return RiskResult(approved=False, reason="Global Kill Switch active", original_signal=signal)

        # 1. Protección por Drawdown (Pérdida Máxima)
        pnl = context.get('unrealized_pnl', 0.0)
        allocation = context.get('allocation', 100.0)
        max_drawdown = context.get('risk_config', {}).get('max_drawdown', 0.05) # 5% por defecto

        # Si perdemos más del drawdown permitido del capital asignado al bot
        if pnl < -(allocation * max_drawdown):
            print(f"[RiskEngine] CRITICAL: Drawdown of ${pnl:.2f} exceeds limit (${allocation * max_drawdown:.2f})")
            return RiskResult(
                approved=False, 
                reason=f"Max drawdown reached ({pnl:.2f})", 
                original_signal=signal,
                emergency_exit=True
            )

        # 2. Protección por Límites de Precios (Hard Limits)
        price = context.get('last_price', 0.0)
        lower_limit = context.get('lower_limit')
        if lower_limit and price < lower_limit:
             print(f"[RiskEngine] CRITICAL: Price (${price:.2f}) broke hard lower limit ($ {lower_limit:.2f})")
             return RiskResult(
                approved=False, 
                reason="Hard lower limit breach", 
                original_signal=signal,
                emergency_exit=True
            )

        # 3. Validación de Exposición General
        # (Sin cambios drásticos aquí)
        if (signal.amount * (signal.price or 0)) > self.max_exposure:
             return RiskResult(approved=False, reason="Max exposure limit reached", original_signal=signal)

        return RiskResult(approved=True, reason="Validated by Risk Engine", original_signal=signal)

    def trigger_kill_switch(self):
        self.kill_switch = True
