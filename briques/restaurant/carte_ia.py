"""Assistant carte — lecture d'une ANCIENNE carte (photo/PDF) → plats structurés.

Synergie de briques, pas de réinvention :
  • l'OCR est délégué à la brique « vision » (souveraine : MarkItDown/Tesseract en local,
    repli hébergé honnête) — on ne refait pas d'OCR ici ;
  • la STRUCTURATION du texte brut en plats (nom / description / prix / catégorie) est
    déléguée à la Gateway LLM (modèle gratuit par défaut, cost-first), OpenAI-compatible.

Ce module ne touche JAMAIS la base : il PROPOSE. Le restaurateur valide/corrige dans le
back-office, puis ajoute à sa carte (chemin authentifié classique). Repli HONNÊTE partout :
si l'OCR ne lit rien ou si le LLM répond illisible, on le DIT — jamais de faux plat inventé.
"""
from __future__ import annotations

import json
import os
import re

import httpx

VISION_URL = os.getenv("VISION_URL", "http://host.docker.internal:5960")
VISION_KEY = os.getenv("VISION_KEY", "")

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")

PROMPT_CARTE = (
    "Tu es un assistant qui NUMÉRISE la carte d'un restaurant. On te donne le TEXTE BRUT "
    "issu d'un OCR de l'ancienne carte (papier ou PDF). Tu en extrais les plats, fidèlement. "
    "Règles STRICTES : n'invente AUCUN plat, AUCUN prix, AUCUNE description absente du texte ; "
    "si un prix est illisible ou absent, mets prix_cents=0 ; déduis la catégorie (Entrées, "
    "Plats, Desserts, Boissons…) seulement si la carte la donne, sinon laisse-la vide. "
    "Convertis les prix en CENTIMES (ex. 12,50 € → 1250)."
)


def _extraire_json_liste(txt: str):
    """Récupère un tableau JSON même entouré de prose / fences markdown (repli : None)."""
    txt = re.sub(r"```(json)?", "", txt or "")
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


async def lire_ocr(contenu_base64: str = "", url: str = "", nom_fichier: str = "") -> dict:
    """Appelle la brique vision (/lire) → {texte, place_holder, backend, note?}.

    Repli HONNÊTE : si vision est injoignable, on renvoie un place_holder qui le dit ;
    l'appelant n'a jamais à joindre l'OCR lui-même."""
    charge = {k: v for k, v in
              {"contenu_base64": contenu_base64, "url": url, "nom_fichier": nom_fichier}.items() if v}
    entetes = {"X-API-Key": VISION_KEY} if VISION_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{VISION_URL}/lire", json=charge, headers=entetes)
            r.raise_for_status()
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"texte": "", "place_holder": True, "backend": "indisponible",
                "note": f"Brique vision (OCR) injoignable : {str(e)[:140]}"}


async def _completer(systeme: str, tache: str) -> str:
    if not GATEWAY_MODEL:
        raise RuntimeError("Aucun modèle LLM configuré (GATEWAY_MODEL).")
    headers = {"Authorization": f"Bearer {GATEWAY_KEY}"} if GATEWAY_KEY else {}
    payload = {"model": GATEWAY_MODEL, "temperature": 0.1,
               "messages": [{"role": "system", "content": systeme},
                            {"role": "user", "content": tache}]}
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(f"{GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


def _plat_propre(o: dict) -> dict | None:
    """Normalise un plat proposé par le LLM (champs sûrs, prix borné). None si pas de nom."""
    if not isinstance(o, dict):
        return None
    nom = str(o.get("nom") or "").strip()
    if not nom:
        return None
    try:
        prix = max(0, int(o.get("prix_cents") or 0))
    except (TypeError, ValueError):
        prix = 0
    return {"nom": nom[:200], "description": str(o.get("description") or "").strip()[:500],
            "prix_cents": prix, "categorie": str(o.get("categorie") or "").strip()[:80]}


async def structurer(texte: str) -> list[dict]:
    """Texte OCR → liste de plats proposés. Repli HONNÊTE : [] si rien d'exploitable."""
    if not (texte or "").strip():
        return []
    tache = (
        "Texte brut OCR de l'ancienne carte :\n" + texte[:12000] + "\n\n"
        'Réponds UNIQUEMENT par un tableau JSON '
        '[{"nom":"...","description":"...","prix_cents":0,"categorie":"..."}], '
        "sans aucun texte autour."
    )
    brut = await _completer(PROMPT_CARTE, tache)
    options = _extraire_json_liste(brut) or []
    plats = [p for p in (_plat_propre(o) for o in options) if p]
    return plats


async def importer(contenu_base64: str = "", url: str = "", nom_fichier: str = "") -> dict:
    """Pipeline complet : OCR (vision) → structuration (Gateway) → proposition.

    Ne PERSISTE rien. Renvoie {ocr:{...}, plats:[...], note}. Toujours honnête sur l'échec :
    OCR vide → plats=[] + la raison ; LLM illisible → plats=[] sans rien inventer."""
    ocr = await lire_ocr(contenu_base64=contenu_base64, url=url, nom_fichier=nom_fichier)
    texte = (ocr.get("texte") or "").strip()
    if ocr.get("place_holder") or not texte:
        return {"ocr": ocr, "plats": [],
                "note": ocr.get("note") or "L'OCR n'a rien pu lire sur ce document."}
    try:
        plats = await structurer(texte)
    except Exception as e:  # noqa: BLE001
        return {"ocr": ocr, "plats": [],
                "note": f"Lecture OK mais structuration LLM indisponible : {str(e)[:140]}"}
    note = "" if plats else "Texte lu, mais aucun plat n'a pu en être extrait avec certitude."
    return {"ocr": {"backend": ocr.get("backend"), "nb_caracteres": ocr.get("nb_caracteres")},
            "plats": plats, "note": note}
