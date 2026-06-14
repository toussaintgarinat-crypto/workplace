"""Moteur de distribution & casting — cœur métier de la brique « personnages ».

Porté de l'atelier Oria (S47) puis rendu AUTONOME et AGNOSTIQUE AU TTS : une « voix »
n'est plus un nom de voix macOS mais un IDENTIFIANT OPAQUE fourni par l'appelant
(ElevenLabs, Azure, OpenAI, peu importe). Aucune dépendance externe : fonctions pures,
sans état caché — on reçoit des structures, on en renvoie de nouvelles.

Une fiche personnage : {id?, nom, role?, description?, voix:{langue→id_voix}}.
"""
from __future__ import annotations

import re


def prochain_id(prefixe: str, pris) -> str:
    """Premier identifiant libre `prefixe{n}` non présent dans `pris` (robuste aux trous)."""
    pris = set(pris or [])
    n = 1
    while f"{prefixe}{n}" in pris:
        n += 1
    return f"{prefixe}{n}"


def cle_perso(nom: str) -> str:
    """Clé de rapprochement (réplique ⇄ fiche) : nom normalisé (casse/espaces)."""
    return re.sub(r"\s+", " ", (nom or "").strip()).upper()


def distribution_texte(personnages: list) -> str:
    """Bloc DISTRIBUTION à injecter dans un prompt d'écriture (vide si aucune fiche).

    C'est le « feed continuité » : on rappelle au modèle d'utiliser exactement ces
    personnages et ces noms d'un passage à l'autre."""
    persos = personnages or []
    if not persos:
        return ""
    lignes = []
    for p in persos:
        bout = f"- {p.get('nom', '?')}"
        if (p.get("role") or "").strip():
            bout += f" — {p['role']}"
        if (p.get("description") or "").strip():
            bout += f" : {p['description']}"
        lignes.append(bout)
    return ("DISTRIBUTION (utilise EXACTEMENT ces personnages et ces noms ; "
            "n'en invente pas d'autres sans nécessité) :\n" + "\n".join(lignes))


def assigner_voix(personnages: list, langue: str, pool: list) -> tuple[list, bool]:
    """Épingle une voix de `pool` à chaque personnage pour `langue` (idempotent).

    Déterministe (ordre de la distribution), NON destructif (respecte les voix déjà
    fixées, manuelles ou auto, tant qu'elles existent dans le pool), et évite de
    réutiliser une voix déjà prise tant que le pool le permet. Retourne (nouvelle
    liste, modifie?). N'altère pas l'entrée."""
    persos = [dict(p, voix=dict(p.get("voix") or {})) for p in (personnages or [])]
    if not pool:
        return persos, False
    prises = [p["voix"][langue] for p in persos if p["voix"].get(langue) in pool]
    modifie = False
    for i, p in enumerate(persos):
        if p["voix"].get(langue) in pool:
            continue
        libre = next((v for v in pool if v not in prises), pool[i % len(pool)])
        p["voix"][langue] = libre
        prises.append(libre)
        modifie = True
    return persos, modifie


def caster(personnages: list, langue: str, intervenants: list, pool: list) -> dict:
    """Affecte une voix à chaque intervenant d'un script. Cœur du différenciateur.

    Un personnage de la distribution garde SA voix (stable d'un script à l'autre) ;
    un intervenant non listé (narrateur, figurant) reçoit une voix tournante du pool,
    de préférence NON déjà attribuée à un personnage nommé.

    `intervenants` : noms tels qu'ils apparaissent dans le script (ordre conservé).
    Retourne {casting: {NOM→id_voix}, personnages: [...]} — la liste de personnages
    enrichie des voix épinglées (à re-persister côté appelant si désiré)."""
    persos, _ = assigner_voix(personnages, langue, pool)
    par_cle = {cle_perso(p["nom"]): p for p in persos if p.get("nom")}
    figees = {p["voix"][langue] for p in persos
              if isinstance(p.get("voix"), dict) and p["voix"].get(langue) in (pool or [])}
    libres = [v for v in (pool or []) if v not in figees] or list(pool or [])
    casting, extra = {}, 0
    for nom in intervenants:
        cle = cle_perso(nom if isinstance(nom, str) else (nom or {}).get("perso", ""))
        affiche = nom if isinstance(nom, str) else (nom or {}).get("perso", "")
        if affiche in casting:
            continue
        fiche = par_cle.get(cle)
        if fiche and fiche["voix"].get(langue):
            casting[affiche] = fiche["voix"][langue]
        elif libres:
            casting[affiche] = libres[extra % len(libres)]
            extra += 1
        else:
            casting[affiche] = ""
    return {"casting": casting, "personnages": persos}


def intervenants_depuis_repliques(repliques: list) -> list:
    """Extrait la liste ordonnée des intervenants depuis des répliques {perso, texte}
    ou une simple liste de noms. Tolérant aux deux formes."""
    out = []
    for r in repliques or []:
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, dict) and r.get("perso"):
            out.append(r["perso"])
    return out
