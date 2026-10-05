"""S238b — non-régression du client OpenAI de la Forge (couple openai/httpx).

openai < 1.55.3 passe encore ``proxies=`` à ``httpx.AsyncClient``, argument retiré par
httpx 0.28 : avec le couple 1.54.0 + 0.28.1, **toute construction** d'``AsyncOpenAI(...)``
levait ``TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'``.
Tout le LLM de la Forge passe par ce client (chat, agents via ``generate_text``, embeddings
RAG) ; la panne est restée invisible de 2026-07-27 à 2026-10-05 parce que ces chemins
n'étaient testés qu'avec des doubles.

Ces tests passent donc par le VRAI code de construction. Seul ajustement : ``max_retries=0``,
injecté par une sous-classe qui délègue au constructeur réel — sans quoi chaque appel sur
un port fermé coûterait 3 tentatives avec back-off. Le port 9 (discard) est fermé : un
``openai.APIConnectionError`` prouve que le client s'est construit et que la requête est
partie ; un ``TypeError`` serait la régression.
"""

import openai
import pytest

PORT_FERME = "http://127.0.0.1:9/v1"


class _SansReessai(openai.AsyncOpenAI):
    """Le vrai ``AsyncOpenAI``, construit à l'identique, mais sans réessai."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_retries", 0)
        kwargs.setdefault("timeout", 5)  # si le port 9 était ouvert : échouer vite, pas 600 s
        super().__init__(*args, **kwargs)


@pytest.fixture
def gateway_fermee(monkeypatch):
    monkeypatch.setattr("app.config.settings.GATEWAY_BASE_URL", PORT_FERME)
    # llm.generate_text importe AsyncOpenAI dans la fonction ; memory l'importe au module.
    monkeypatch.setattr(openai, "AsyncOpenAI", _SansReessai)
    monkeypatch.setattr("app.memory.AsyncOpenAI", _SansReessai)
    monkeypatch.setattr("app.react_executor.AsyncOpenAI", _SansReessai)


def test_client_openai_se_construit_avec_les_reglages_reels():
    """Construction telle que la font llm.py, memory.py et les routeurs de chat."""
    from app.config import settings

    client = openai.AsyncOpenAI(base_url=settings.GATEWAY_BASE_URL, api_key=settings.GATEWAY_API_KEY)
    assert client is not None


async def test_generate_text_atteint_le_reseau(gateway_fermee):
    from app.llm import generate_text

    with pytest.raises(openai.APIConnectionError):
        await generate_text("bonjour", provider="gateway", model="openai/gpt-4o-mini")


async def test_embed_local_atteint_le_reseau(gateway_fermee):
    from app import memory

    with pytest.raises(openai.APIConnectionError):
        await memory._embed_local(["bonjour"])


async def test_client_react_atteint_le_reseau(gateway_fermee):
    """Fabrique du mode ReAct — même construction que chat.py, ws.py, pipeline_templates.py."""
    from app.react_executor import _client

    with pytest.raises(openai.APIConnectionError):
        await _client().chat.completions.create(
            model="openai/gpt-4o-mini", messages=[{"role": "user", "content": "bonjour"}])
