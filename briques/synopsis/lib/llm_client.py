"""LLM Client — Gateway-aware with standalone fallback.

Priority:
  1. GATEWAY_URL (Workplace LiteLLM) — OpenAI-compatible /v1/chat/completions
  2. OPENROUTER_API_KEY — direct OpenRouter API
  3. OPENCODE_GO_API_KEY — direct OpenCode Go API
"""

import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
MAX_RETRIES = 2


def llm_complete(prompt: str, model: str = "", system: str = "", temperature: float = 0.3) -> str:
    model = model or DEFAULT_MODEL
    gateway_url = os.getenv("GATEWAY_URL", "").rstrip("/")
    gateway_key = os.getenv("GATEWAY_KEY", os.getenv("LITELLM_MASTER_KEY", ""))

    if gateway_url:
        return _complete_openai_compatible(
            f"{gateway_url}/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=gateway_key,
        )

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        return _complete_openai_compatible(
            "https://openrouter.ai/api/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=openrouter_key,
            extra_headers={"HTTP-Referer": "https://synopsis.local", "X-Title": "Synopsis"},
        )

    opencode_key = os.getenv("OPENCODE_GO_API_KEY", "")
    if opencode_key:
        return _complete_openai_compatible(
            "https://opencode.ai/zen/go/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=opencode_key,
        )

    raise RuntimeError(
        "Aucun fournisseur LLM configuré. "
        "Définissez GATEWAY_URL, OPENROUTER_API_KEY ou OPENCODE_GO_API_KEY."
    )


def _complete_openai_compatible(
    base_url: str,
    prompt: str,
    model: str,
    system: str = "",
    temperature: float = 0.3,
    api_key: str = "",
    extra_headers: dict = None,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 32000,
    }

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = httpx.post(base_url, json=payload, headers=headers, timeout=180)
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                last_err = f"Rate limited (attempt {attempt + 1})"
                continue
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        except httpx.RequestError as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(2)

    raise RuntimeError(f"LLM call failed after {MAX_RETRIES + 1} attempts: {last_err}")
