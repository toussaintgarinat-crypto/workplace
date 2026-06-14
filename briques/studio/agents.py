"""Équipe créative INTERNALISÉE + pont Gateway (S51).

Dans Oria, les 6 agents du studio étaient des `AgentDefinition` rangés en base par
`world_id` (couplage à `get_db` + au monde). Ici, ils deviennent l'IP de la brique :
6 prompts système figés, exposés par une petite registre en mémoire. Plus de DB, plus de
`world_id` — `agent("Scénariste")` suffit.

Le pont Gateway (`_gateway_answer`) est repris tel quel d'`agents_router` : cascade de
modèles GRATUITS d'abord (priorité coût Workplace), payant en tout dernier recours. La
Gateway et la clé viennent de l'environnement (BYO key possible).
"""
import os
from dataclasses import dataclass

import httpx

# ── Gateway (cost-first, BYO key possible via l'environnement) ───
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")
GATEWAY_KEY = os.getenv("GATEWAY_KEY") or os.getenv("LLM_API_KEY") or ""

# Cascade GRATUITE : on essaie d'abord le modèle demandé, puis des modèles gratuits si l'un
# est rate-limité (429) ou KO. Le payant n'arrive qu'en tout dernier recours.
FREE_CASCADE = [
    "free/google/gemma-4-31b-it",
    "free/google/gemma-4-26b-a4b-it",
    "free/qwen/qwen3-next-80b-a3b-instruct",
    "free/moonshotai/kimi-k2.6",
    "openai/gpt-4o-mini",  # repli payant ultime
]


async def _gateway_answer(base: str, model: str, system: str, message: str) -> str:
    """Réponse d'un agent via la Gateway LLM (OpenAI-compatible), cascade gratuite d'abord."""
    candidats = []
    for m in [model] + FREE_CASCADE:
        if m and m not in candidats:
            candidats.append(m)
    url = f"{base.rstrip('/')}/v1/chat/completions"
    dernier = "aucune tentative"
    async with httpx.AsyncClient(timeout=90.0) as client:
        for m in candidats:
            try:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
                    json={
                        "model": m,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": message},
                        ],
                    },
                )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                dernier = f"{m}: HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                dernier = f"{m}: {str(e)[:80]}"
    raise RuntimeError(f"Cascade Gateway épuisée ({dernier})")


# ── L'équipe créative (prompts internes = IP de la brique) ───────
# (nom, emoji, x, y, prompt). x/y = position sur la carte d'un monde Oria : conservée
# pour le hook d'intégration optionnel (S53), inutile au fonctionnement de la brique.
EQUIPE = [
    ("Showrunner — Architecte Narratif", "🎬", 2.5, 3.0,
     "Tu es le SHOWRUNNER (Architecte Narratif) d'un studio d'audio-séries interactives type "
     "'Livre dont vous êtes le héros'. Tu crées la BIBLE (univers, personnages, ton), cartographies "
     "l'ARBRE DES CHOIX et garantis la cohérence entre TOUTES les branches. Tu ne rédiges pas les dialogues. "
     "Réponds en français, structuré et concis."),
    ("Scénariste", "✍️", 2.5, 5.5,
     "Tu es le SCÉNARISTE. À partir d'un synopsis fourni par le Showrunner, tu rédiges le SCRIPT complet "
     "(dialogues + action) d'un épisode COURT (10-15 min), rythme soutenu. Personnages en MAJUSCULES, "
     "didascalies entre parenthèses. Tu n'inventes pas l'univers et n'ajoutes pas les balises son. Réponds en français."),
    ("Script Doctor", "🩺", 2.5, 8.0,
     "Tu es le SCRIPT DOCTOR. Tu VALIDES un script, traques les incohérences, et injectes les balises "
     "[SFX:...]/[AMBIANCE:...]/[MUSIQUE:...]. Tu rends un script gelé. D'abord la liste des corrections, "
     "puis le script balisé. Réponds en français."),
    ("Directeur de Casting (Audio)", "🎙️", 7.5, 3.0,
     "Tu es le DIRECTEUR DE CASTING AUDIO. Tu gères l'identité vocale des personnages : une voix IA fixe "
     "par protagoniste + les curseurs d'émotion par scène. À partir d'un script balisé, tu rends une fiche "
     "de casting (voix + émotion/intensité par réplique clé). Réponds en français."),
    ("Sound Designer (Mixeur)", "🎚️", 7.5, 5.5,
     "Tu es le SOUND DESIGNER/MIXEUR. Tu convertis les balises [SFX]/[AMBIANCE]/[MUSIQUE] en plan sonore "
     "concret (son réel, durée, placement, nappe musicale) et tu spécifies le DUCKING. Tu rends une feuille "
     "de montage chronologique. Réponds en français."),
    ("Directeur Artistique (Visuels)", "🎨", 7.5, 8.0,
     "Tu es le DIRECTEUR ARTISTIQUE. Tu crées la couverture de chaque épisode : un PROMPT d'illustration "
     "ultra-précis (style, cadrage, lumière, palette, contraintes anti-artefacts) + une checklist QA. "
     "Réponds en français."),
]


@dataclass(frozen=True)
class Agent:
    """Un membre de l'équipe créative — équivalent interne d'un ancien `AgentDefinition`."""
    nom: str
    avatar_emoji: str
    map_x: float
    map_y: float
    system_prompt: str


AGENTS = [Agent(nom, emoji, x, y, prompt) for nom, emoji, x, y, prompt in EQUIPE]


def agent(mot: str) -> Agent:
    """Retrouve un agent par mot-clé dans son nom (ex. « Scénariste », « Showrunner »).

    Remplace `_agent(db, world_id, mot)` : l'équipe est interne, toujours présente."""
    for a in AGENTS:
        if mot.lower() in a.nom.lower():
            return a
    raise KeyError(f"Agent « {mot} » inconnu de l'équipe du studio.")


async def demander(ag: Agent, tache: str) -> str:
    """Fait répondre un agent EN PERSONNAGE via la Gateway (modèle/clé d'environnement)."""
    return await _gateway_answer(GATEWAY_URL, GATEWAY_MODEL, ag.system_prompt, tache)
