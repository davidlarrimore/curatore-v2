import httpx
from typing import Dict, Any, List
from .config import Settings

class LLMClient:
    """
    Thin OpenAI-compatible client via HTTP. Keeps us MCP-friendly and vendor-neutral.
    """
    def __init__(self, cfg: Settings):
        self.base = cfg.OPENAI_BASE_URL.rstrip("/")
        self.api_key = cfg.OPENAI_API_KEY
        self.model = cfg.OPENAI_MODEL
        self.timeout = cfg.OPENAI_TIMEOUT
        self.verify = cfg.OPENAI_VERIFY_SSL

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2, max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout, verify=self.verify) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()

    async def health_probe(self) -> Dict[str, Any]:
        try:
            content = await self.chat(
                [{"role": "system", "content": "Reply 'ok'"},
                 {"role": "user", "content": "ok"}],
                temperature=0, max_tokens=5,
            )
            return {"connected": True, "response": content}
        except Exception as e:
            return {"connected": False, "error": str(e)}