from app.llm.client import LLMClient


class EmbeddingIndisponible(Exception):
    """L'embedder n'a pas pu vectoriser le texte (Gateway injoignable, modèle absent…).

    Avant S238, l'échec était masqué par un vecteur pseudo-aléatoire constant (graine 42) :
    stocké comme réel à l'écriture, et donnant en recherche des scores tous égaux présentés
    comme un succès. L'échec est désormais signalé ; chaque appelant décide (embedding
    différé, recherche lexicale seule, 503)."""


class Embedder:
    def __init__(self):
        self.client = LLMClient()

    async def embed_text(self, text: str) -> list[float] | None:
        if not text or not text.strip():
            return None
        try:
            return await self.client.embed(text[:8000])
        except Exception as exc:
            raise EmbeddingIndisponible(str(exc) or type(exc).__name__) from exc

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [await self.embed_text(text) for text in texts]
