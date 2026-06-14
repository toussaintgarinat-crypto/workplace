"""Mapping provider/model → modèle gateway (S128)."""

from app.llm import AVAILABLE_PROVIDERS, gateway_model


def test_gateway_model_prefixes_provider():
    assert gateway_model("openai", "gpt-4o") == "openai/gpt-4o"
    assert gateway_model("ollama", "llama3.2") == "ollama/llama3.2"


def test_gateway_model_passthrough_for_prefixed():
    # gateway/openrouter ou modèle déjà préfixé → pas de double préfixe
    assert gateway_model("gateway", "openai/gpt-4o") == "openai/gpt-4o"
    assert gateway_model("openrouter", "anthropic/claude-sonnet-4-6") == "anthropic/claude-sonnet-4-6"
    assert gateway_model("openai", "anthropic/claude") == "anthropic/claude"
    # OpenCode Go : le préfixe `go/` est le model_name de la Gateway, jamais re-préfixé.
    assert gateway_model("opencode", "go/deepseek-v4-pro") == "go/deepseek-v4-pro"


def test_gateway_model_defaults(monkeypatch):
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_PROVIDER", "ollama")
    monkeypatch.setattr("app.config.settings.DEFAULT_LLM_MODEL", "llama3.2")
    assert gateway_model(None, None) == "ollama/llama3.2"


def test_available_providers_shape():
    ids = {p["id"] for p in AVAILABLE_PROVIDERS}
    assert {"ollama", "openai", "anthropic", "gateway"} <= ids
    for p in AVAILABLE_PROVIDERS:
        assert isinstance(p["models"], list) and p["models"]
