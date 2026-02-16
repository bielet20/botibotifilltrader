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
