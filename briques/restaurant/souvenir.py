"""Résumé de soirée — un petit souvenir de la tablée en fin de repas (S85).

À la fin du repas, les convives peuvent garder un mot doux récapitulant leur soirée :
le surnom de la tablée, les plats partagés, le total. Le ton chaleureux/festif est
délégué à la Gateway LLM (modèle gratuit par défaut, cost-first), comme `carte_ia.py`.

Repli HONNÊTE : si la Gateway est injoignable ou répond mal, on retombe sur un résumé
FACTUEL construit localement (plats réellement commandés + total) — JAMAIS d'anecdote
inventée, jamais de fausse promesse. Le champ `genere_par` dit toujours la vérité
(« ia » ou « local »). Ce module ne touche pas la base : on lui passe l'état déjà calculé.
"""
from __future__ import annotations

import os

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")

PROMPT_SOUVENIR = (
    "Tu écris un petit SOUVENIR chaleureux et festif de fin de repas pour une tablée de "
    "restaurant. On te donne les faits réels de la soirée (surnom de la tablée, plats "
    "commandés, total). Règles STRICTES : reste FIDÈLE aux faits, n'invente AUCUN plat ni "
    "détail absent ; pas de prix dans le texte sauf le total ; 2 à 4 phrases, ton convivial "
    "et bienveillant, en {langue}. Tutoie la tablée. Termine par un mot d'au revoir."
)

_LANGUES = {"fr": "français", "en": "anglais", "es": "espagnol"}


def _plats_de(convives: list[dict]) -> list[str]:
    """Agrège les plats réellement commandés sur la table (libellé « 2× Burger »)."""
    compte: dict[str, int] = {}
    ordre: list[str] = []
    for c in convives or []:
        for d in c.get("details", []) or []:
            nom = str(d.get("nom_plat") or "").strip()
            if not nom:
                continue
            q = int(d.get("quantite") or 1)
            if nom not in compte:
                compte[nom] = 0
                ordre.append(nom)
            compte[nom] += q
    return [f"{compte[n]}× {n}" for n in ordre]


def _total_str(total_cents: int, devise: str) -> str:
    return f"{total_cents / 100:.2f} {devise}".replace(".", ",")


def resume_factuel(*, restaurant_nom: str, table_numero: str, nom_session: str,
                   convives: list[dict], total_cents: int, devise: str, lang: str = "fr") -> str:
    """Résumé FACTUEL local (sans LLM) : surnom + plats + total. Honnête, jamais inventé."""
    plats = _plats_de(convives)
    en = lang == "en"
    tablee = nom_session.strip() or f"Table {table_numero}"
    if en:
        debut = f"A memory from « {tablee} » at {restaurant_nom}."
        menu = ("On the menu: " + ", ".join(plats) + ".") if plats else "A lovely moment shared together."
        fin = f"Total: {_total_str(total_cents, devise)}. Thanks and see you soon!"
    else:
        debut = f"Souvenir de « {tablee} » chez {restaurant_nom}."
        menu = ("Au menu : " + ", ".join(plats) + ".") if plats else "Un joli moment partagé ensemble."
        fin = f"Total : {_total_str(total_cents, devise)}. Merci et à bientôt !"
    return " ".join([debut, menu, fin])


async def _completer(systeme: str, tache: str) -> str:
    if not GATEWAY_MODEL:
        raise RuntimeError("Aucun modèle LLM configuré (GATEWAY_MODEL).")
    headers = {"Authorization": f"Bearer {GATEWAY_KEY}"} if GATEWAY_KEY else {}
    payload = {"model": GATEWAY_MODEL, "temperature": 0.7,
               "messages": [{"role": "system", "content": systeme},
                            {"role": "user", "content": tache}]}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


async def resumer(*, restaurant_nom: str, table_numero: str, nom_session: str,
                  convives: list[dict], total_cents: int, devise: str, lang: str = "fr") -> dict:
    """Construit le souvenir de soirée. Tente la Gateway (ton festif), retombe sur le résumé
    FACTUEL local en cas d'échec. Renvoie {texte, genere_par:"ia"|"local", note}."""
    factuel = resume_factuel(restaurant_nom=restaurant_nom, table_numero=table_numero,
                             nom_session=nom_session, convives=convives,
                             total_cents=total_cents, devise=devise, lang=lang)
    plats = _plats_de(convives)
    if not plats:
        # Rien commandé : le factuel suffit (pas de matière pour une « anecdote »).
        return {"texte": factuel, "genere_par": "local",
                "note": "Aucun plat commandé pour cette session."}
    langue = _LANGUES.get(lang, "français")
    tablee = nom_session.strip() or (f"Table {table_numero}")
    tache = (
        f"Faits de la soirée :\n"
        f"- Restaurant : {restaurant_nom}\n- Tablée : {tablee}\n"
        f"- Plats partagés : {', '.join(plats)}\n- Total : {_total_str(total_cents, devise)}\n\n"
        f"Écris le souvenir (2 à 4 phrases), uniquement le texte."
    )
    try:
        texte = await _completer(PROMPT_SOUVENIR.format(langue=langue), tache)
    except Exception:  # noqa: BLE001 — repli honnête, jamais d'erreur opaque côté client
        return {"texte": factuel, "genere_par": "local",
                "note": "Résumé festif indisponible (assistant hors ligne) : voici le récap."}
    if not texte:
        return {"texte": factuel, "genere_par": "local", "note": "Réponse vide : récap factuel."}
    return {"texte": texte[:1200], "genere_par": "ia", "note": ""}
