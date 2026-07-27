#!/usr/bin/env python3
"""
Synchronise les modèles gratuits OpenRouter dans litellm_config.yaml.

Lancé par `make start` (et `make sync`) DANS CE DOSSIER. Le lanceur racine
« Lancer Workplace.command » et le déploiement HP font un `docker compose up -d`
générique : ils ne passent PAS par ici, donc après un déploiement direct il faut
lancer `make sync` à la main, sinon la liste fige.

À relancer régulièrement : un modèle gratuit d'OpenRouter peut passer payant ou
disparaître du jour au lendemain, et litellm remonte alors des NotFoundError en
boucle sur ce slug (« model is unavailable for free … use this slug instead »).
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

CONFIG = Path(__file__).parent / "litellm_config.yaml"
TOP_N = int(os.environ.get("FREE_MODELS_TOP_N", "12"))
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

MARKER_START = "  # AUTO-FREE-MODELS-START"
MARKER_END = "  # AUTO-FREE-MODELS-END"


def fetch_free_models():
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())

    def gratuit(m: dict) -> bool:
        p = m.get("pricing", {})
        return str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0"

    def utile_pour_assistant(m: dict) -> bool:
        # L'assistant du Cœur EXIGE le function-calling et du texte (pas audio/image).
        sp = m.get("supported_parameters") or []
        modality = (m.get("architecture", {}) or {}).get("modality", "") or ""
        return "tools" in sp and "text" in modality

    free = [m for m in data["data"] if gratuit(m) and utile_pour_assistant(m)]
    free.sort(key=lambda m: m.get("context_length", 0), reverse=True)
    return free[:TOP_N]


def model_entry(m: dict) -> str:
    mid = m["id"]
    parts = mid.split("/")
    provider = parts[0] if len(parts) > 1 else "unknown"
    slug = parts[-1].replace(":free", "").replace(":", "-")
    name = f"free/{provider}/{slug}"
    ctx = m.get("context_length", "?")
    # Borné : les gratuits OpenRouter rate-limitent souvent et peuvent PENDRE au lieu
    # de renvoyer un 429 rapide → timeout court + 0 retry pour que la cascade du Cœur
    # bascule vite sur le gratuit suivant, puis sur le repli payant. Cf. Workplace S17.
    return (
        f"  - model_name: {name}\n"
        f"    litellm_params:\n"
        f"      model: openrouter/{mid}\n"
        f"      api_key: os.environ/OPENROUTER_API_KEY\n"
        f"      api_base: https://openrouter.ai/api/v1\n"
        f"      timeout: 10\n"
        f"      num_retries: 0\n"
        f"      # context: {ctx}"
    )


def sync():
    if not API_KEY:
        print("[sync_free_models] OPENROUTER_API_KEY absent — skip", file=sys.stderr)
        return

    try:
        models = fetch_free_models()
    except Exception as e:
        print(f"[sync_free_models] Erreur API OpenRouter: {e} — skip", file=sys.stderr)
        return

    content = CONFIG.read_text()
    if MARKER_START not in content:
        print("[sync_free_models] Marqueurs absents du config — skip", file=sys.stderr)
        return

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries = "\n".join(model_entry(m) for m in models)
    new_section = f"{MARKER_START} — {ts} ({len(models)} modèles)\n{entries}\n{MARKER_END}"

    updated = re.sub(
        rf"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
        new_section,
        content,
        flags=re.DOTALL,
    )
    CONFIG.write_text(updated)

    print(f"[sync_free_models] {len(models)} modèles gratuits synchronisés:")
    for m in models:
        print(f"  free/{m['id'].split('/')[0]}/{m['id'].split('/')[-1].replace(':free','')} "
              f"(ctx: {m.get('context_length','?')})")


if __name__ == "__main__":
    sync()
