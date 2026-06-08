
from app.llm.client import LLMClient


class Embedder:
    def __init__(self):
        self.client = LLMClient()

    async def embed_text(self, text: str) -> list[float]:
        if not text.strip():
            return [0.0] * 384
        try:
            return await self.client.embed(text[:8000])
        except Exception:
            import numpy as np
            rng = np.random.default_rng(42)
            return rng.uniform(-0.1, 0.1, 384).tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            results.append(await self.embed_text(text))
        return results
