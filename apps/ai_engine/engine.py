import httpx
import asyncio
import os

class AIEngine:
    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name
        self.ollama_url = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")

    async def generate_explanation(self, trade_data: dict) -> str:
        prompt = f"""
        Analyze this trade as a professional algorithmic trading assistant:
        Symbol: {trade_data.get('symbol')}
        Side: {trade_data.get('side')}
        Price: {trade_data.get('price')}
        Amount: {trade_data.get('amount')}
        Strategy ID: {trade_data.get('bot_id')}
        
        Provide a concise, 1-2 sentence explanation of why this trade occurred based on typical momentum or trend-following logic. 
        Focus on being professional and insightful.
        """
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model_name,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                if response.status_code == 200:
                    return response.json().get("response", "No response from AI.")
                else:
                    return "AI Insight: Trade executed based on strategy parameters. (Local LLM unavailable)"
        except Exception as e:
            return f"AI Insight: Strategy signal triggered at {trade_data.get('price')}. (Engine offline: {str(e)})"

    async def suggest_optimization(self, bot_performance: dict) -> dict:
        # Placeholder for more complex logic
        return {
            "suggested_changes": {"ema_window": 20, "take_profit": 0.05}
        }

    async def evaluate_take_profit(self, position_context: dict) -> dict:
        """Rule-based AI take-profit evaluator with dynamic thresholding."""
        profit_pct = float(position_context.get("profit_pct") or 0.0)
        unrealized_pnl = float(position_context.get("unrealized_pnl") or 0.0)
        volatility_pct = abs(float(position_context.get("volatility_pct") or 0.0))
        trend_strength = float(position_context.get("trend_strength") or 0.0)

        min_profit_pct = max(0.001, float(position_context.get("min_profit_pct") or 0.006))
        hard_take_profit_pct = max(min_profit_pct, float(position_context.get("hard_take_profit_pct") or 0.02))

        dynamic_target = min(hard_take_profit_pct, max(min_profit_pct, min_profit_pct + (volatility_pct * 1.6)))
        if trend_strength < 0:
            dynamic_target = max(min_profit_pct * 0.7, dynamic_target * 0.85)

        should_take_profit = unrealized_pnl > 0 and profit_pct >= dynamic_target
        reason = (
            f"profit_pct={profit_pct:.5f} >= target={dynamic_target:.5f}"
            if should_take_profit
            else f"profit_pct={profit_pct:.5f} < target={dynamic_target:.5f}"
        )

        return {
            "should_take_profit": should_take_profit,
            "target_profit_pct": round(dynamic_target, 6),
            "reason": reason,
            "source": "ai_rule_engine",
        }
