from abc import ABC, abstractmethod
from apps.shared.models import TradeSignal, RiskResult, ExecutionResult

class BaseStrategy(ABC):
    @abstractmethod
    async def analyze(self, market_data: dict) -> TradeSignal:
        pass

class BaseRiskProvider(ABC):
    @abstractmethod
    async def validate(self, signal: TradeSignal) -> RiskResult:
        pass

class BaseExecutionProvider(ABC):
    @abstractmethod
    async def execute(self, signal: TradeSignal) -> ExecutionResult:
        pass
