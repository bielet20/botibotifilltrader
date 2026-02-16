from apps.shared.interfaces import BaseRiskProvider
from apps.shared.models import TradeSignal, RiskResult

class RiskEngine(BaseRiskProvider):
    def __init__(self, global_kill_switch: bool = False, max_exposure: float = 1000000):
        self.kill_switch = global_kill_switch
        self.max_exposure = max_exposure
        self.current_exposure = 0.0

    async def validate(self, signal: TradeSignal) -> RiskResult:
        if self.kill_switch:
            return RiskResult(approved=False, reason="Global Kill Switch active", original_signal=signal)
        
        # Simple exposure check placeholder
        if self.current_exposure + (signal.amount * (signal.price or 0)) > self.max_exposure:
             return RiskResult(approved=False, reason="Max exposure limit reached", original_signal=signal)

        return RiskResult(approved=True, reason="Validated by Risk Engine", original_signal=signal)

    def trigger_kill_switch(self):
        self.kill_switch = True
