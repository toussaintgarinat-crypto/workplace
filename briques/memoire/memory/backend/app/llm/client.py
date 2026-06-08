
from app.config import settings


class LLMClient:
    def __init__(self):
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url
        self._client = None

    async def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import AsyncOpenAI

        if self.provider == "ollama":
            self._client = AsyncOpenAI(
                base_url=self.base_url or "http://localhost:11434/v1",
                api_key="ollama",
            )
        elif self.provider == "llamacpp":
            self._client = AsyncOpenAI(
                base_url=self.base_url or "http://localhost:8080/v1",
                api_key="not-needed",
            )
        else:
            self._client = AsyncOpenAI(
                api_key=self.api_key or "",
                base_url=self.base_url,
            )
        return self._client

    async def chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 1024) -> str:
        client = await self._get_client()
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def embed(self, text: str) -> list[float]:
        client = await self._get_client()
        embed_model = settings.embedding_model
        response = await client.embeddings.create(
            model=embed_model,
            input=text,
        )
        return response.data[0].embedding
