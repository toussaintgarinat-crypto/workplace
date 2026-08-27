"""Studio audio-séries — logique métier (extraite d'Oria, S51).

Co-création humain ↔ équipe créative : à chaque dimension (genre, univers,
personnages, intrigue, choix…), un agent PROPOSE, l'humain DÉCIDE. La bible prête, la
production d'un épisode s'enchaîne (Scénariste → Script Doctor). Structure en livre
(Série → Cycles → Tomes → Chapitres), épisodes d'écoute ~12 min, multilingue, journal
de continuité, arbre des choix, synergie images.

Ce module ne contient que de la LOGIQUE PURE + la persistance JSON : aucune dépendance à
FastAPI, à une base, ni à un `world_id`. L'équipe créative vient de `agents` (prompts
internalisés), le LLM de la Gateway via `agents._gateway_answer`.
"""
import os
import re
import json
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional

import httpx

from agents import (  # noqa: F401  (réexportés pour les tests / endpoints)
    GATEWAY_URL,
    GATEWAY_MODEL,
    _gateway_answer,
    agent,
    demander as _demander,
)

# Alias historiques (parité avec l'ancien atelier_router → diff minimal des tests).
GW_URL = GATEWAY_URL
GW_MODEL = GATEWAY_MODEL

# ── Persistance fichier (volume propre à la brique) ──────────────
# Séries stockées en JSON, une par fichier. Le dossier vient de l'environnement → volume
# Docker dédié (plus de /app/uploads partagé avec Oria). Tests : surchargé en temp dir.
ATELIERS_DIR = os.getenv("STUDIO_DIR", "/data/ateliers")
os.makedirs(ATELIERS_DIR, exist_ok=True)

# Profils lecteurs (S231) : un fichier par profil, sous-dossier dédié pour ne jamais
# collisionner avec un fichier de série (même motif de nommage : uuid4 hex).
PROFILS_DIR = os.path.join(ATELIERS_DIR, "profils")
os.makedirs(PROFILS_DIR, exist_ok=True)

# Service « voix » sur l'hôte macOS (say + ffmpeg) — le conteneur le joint ainsi.
VOIX_URL = os.getenv("VOIX_URL", "http://host.docker.internal:5810")
VOIX_FALLBACK = ["Thomas", "Jacques", "Flo", "Eddy", "Grandpa", "Grandma"]

# Brique « images » (5950) : moteur d'illustration (ComfyUI + repli placeholder honnête).
IMAGES_URL = os.getenv("IMAGES_URL", "http://host.docker.internal:5950")
IMAGES_PUBLIC = os.getenv("IMAGES_PUBLIC_URL", "http://localhost:5950")

# Brique « video » (5970) : moteur vidéo (fal/Replicate/Luma/Runway/Gateway + repli honnête).
VIDEO_URL = os.getenv("VIDEO_URL", "http://host.docker.internal:5970")
VIDEO_PUBLIC = os.getenv("VIDEO_PUBLIC_URL", "http://localhost:5970")

# Découpage en ÉPISODES d'écoute (~12 min) à partir des CHAPITRES.
CIBLE_EPISODE_SECONDES = 12 * 60        # durée cible d'un épisode d'écoute
CHAPITRES_PAR_EPISODE_DEFAUT = 4        # repli tant qu'aucun chapitre n'est sonorisé

# Quel agent (par mot-clé dans son nom) anime quelle étape de la bible.
DIMENSION_AGENT = {
    "genre":       "Showrunner",
    "univers":     "Showrunner",
    "personnages": "Showrunner",
    "intrigue":    "Showrunner",
    "synopsis":    "Showrunner",
    "choix":       "Showrunner",
}
ORDRE = ["genre", "univers", "personnages", "intrigue", "choix"]


def _path(serie_id: str) -> str:
    return os.path.join(ATELIERS_DIR, f"{serie_id}.json")


def _load(serie_id: str) -> dict:
    p = _path(serie_id)
    if not os.path.exists(p):
        raise FileNotFoundError(serie_id)
    with open(p, encoding="utf-8") as f:
        return _normaliser(json.load(f))


def _save(serie: dict) -> None:
    with open(_path(serie["id"]), "w", encoding="utf-8") as f:
        json.dump(serie, f, ensure_ascii=False, indent=2)


def _profil_path(profil_id: str) -> str:
    return os.path.join(PROFILS_DIR, f"{profil_id}.json")


def _load_profil(profil_id: str) -> dict:
    p = _profil_path(profil_id)
    if not os.path.exists(p):
        raise FileNotFoundError(profil_id)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_profil(profil: dict) -> None:
    with open(_profil_path(profil["id"]), "w", encoding="utf-8") as f:
        json.dump(profil, f, ensure_ascii=False, indent=2)


# ── Journal d'écoute/choix par profil (V1 saga familiale) ────────
# Un fichier par profil, préfixé par le même id que le profil (portabilité, cf. ADR
# 2026-08-18) : append-only, gardé séparé de PROFILS_DIR/{profil_id}.json pour ne pas
# mélanger l'identité/config du profil (rarement modifiée) et son activité (modifiée à
# chaque écoute).

def _journal_path(profil_id: str) -> str:
    return os.path.join(PROFILS_DIR, f"{profil_id}-journal.json")


def _load_journal(profil_id: str) -> list:
    p = _journal_path(profil_id)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("evenements", [])


def _ajouter_evenement(profil_id: str, evenement: dict) -> dict:
    """Ajoute un événement au journal d'un profil (append-only). Complète `id`/`quand`
    si absents ; ne les écrase jamais s'ils sont déjà fournis."""
    complet = dict(evenement)
    complet.setdefault("id", uuid.uuid4().hex)
    complet.setdefault("quand", datetime.now(timezone.utc).isoformat())
    evenements = _load_journal(profil_id)
    evenements.append(complet)
    with open(_journal_path(profil_id), "w", encoding="utf-8") as f:
        json.dump({"profil_id": profil_id, "evenements": evenements}, f,
                   ensure_ascii=False, indent=2)
    return complet


# ── Nom de famille cosmétique (V1 saga familiale) ─────────────────
# PAS l'entité `Famille` écartée par l'ADR 2026-08-18 : aucune donnée d'enfant ici,
# uniquement une étiquette d'affichage au niveau du compte (`cree_par`).
COMPTES_DIR = os.path.join(ATELIERS_DIR, "comptes")
os.makedirs(COMPTES_DIR, exist_ok=True)


def _compte_path(identite: str) -> str:
    """Fichier haché : `identite` peut être une clé API, jamais exposée en clair dans un
    nom de fichier listable."""
    h = hashlib.sha256(identite.encode("utf-8")).hexdigest()[:16]
    return os.path.join(COMPTES_DIR, f"{h}.json")


def _load_compte(identite: str) -> dict:
    p = _compte_path(identite)
    if not os.path.exists(p):
        return {"nom_famille": None}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_compte(identite: str, compte: dict) -> None:
    with open(_compte_path(identite), "w", encoding="utf-8") as f:
        json.dump(compte, f, ensure_ascii=False, indent=2)


# ── Hiérarchie : Série → Cycles → Tomes → Chapitres (= episodes) ──

def _tous_tomes(serie: dict) -> list:
    """Tous les tomes, à plat, dans l'ordre cycle puis tome."""
    return [t for c in serie.get("cycles", []) for t in c.get("tomes", [])]


def _tome_de(serie: dict, tome_id: str) -> tuple:
    """Retrouve (cycle, tome) pour un tome_id, ou (None, None)."""
    for c in serie.get("cycles", []):
        for t in c.get("tomes", []):
            if t["id"] == tome_id:
                return c, t
    return None, None


def _contexte_volume(serie: dict) -> str:
    """Résumés du cycle ET du tome actifs, pour que les volumes pilotent l'écriture."""
    cycle, tome = _tome_de(serie, serie.get("tome_actif"))
    bouts = []
    if cycle and (cycle.get("resume") or "").strip():
        bouts.append(f"Cycle « {cycle['titre']} » : {cycle['resume'].strip()}")
    if tome and (tome.get("resume") or "").strip():
        bouts.append(f"Tome « {tome['titre']} » : {tome['resume'].strip()}")
    if not bouts:
        return ""
    return ("Arc du volume où s'écrit ce chapitre (respecte-le impérativement) :\n"
            + "\n".join(f"- {b}" for b in bouts) + "\n\n")


def _chapitres_du_tome(serie: dict, tome_id: str) -> list:
    """Les chapitres écrits dans un tome, dans l'ordre (`n`)."""
    return sorted((e for e in serie.get("episodes", []) if e.get("tome_id") == tome_id),
                  key=lambda e: e.get("n", 0))


def _bilan_structurel(serie: dict, tome: dict) -> dict:
    """Faits OBJECTIFS sur l'avancement d'un tome (sans LLM)."""
    chapitres = _chapitres_du_tome(serie, tome["id"])
    dernier = chapitres[-1] if chapitres else None
    return {
        "nb_chapitres": len(chapitres),
        "a_un_arc": bool((tome.get("resume") or "").strip()),
        "statut": tome.get("statut", "en_cours"),
        "finit_sur_cliffhanger": bool(dernier and dernier.get("fin_episode")),
    }


def _next_id(prefixe: str, pris: set) -> str:
    n = 1
    while f"{prefixe}{n}" in pris:
        n += 1
    return f"{prefixe}{n}"


def _normaliser(serie: dict) -> dict:
    """Garantit la hiérarchie et rattache les chapitres orphelins (rétrocompat)."""
    if not serie.get("cycles"):
        serie["cycles"] = [{
            "id": "c1", "numero": 1, "titre": "Cycle 1", "resume": "",
            "tomes": [{"id": "t1", "numero": 1, "titre": "Tome 1", "resume": ""}],
        }]
    if not _tous_tomes(serie):
        serie["cycles"][0].setdefault("tomes", []).append(
            {"id": "t1", "numero": 1, "titre": "Tome 1", "resume": ""})

    ids_tomes = [t["id"] for t in _tous_tomes(serie)]
    premier = ids_tomes[0]
    if serie.get("tome_actif") not in ids_tomes:
        serie["tome_actif"] = premier
    for ep in serie.get("episodes", []):
        if ep.get("tome_id") not in ids_tomes:
            ep["tome_id"] = premier
    serie.setdefault("personnages", [])   # distribution structurée (rétrocompat)
    canon = serie.setdefault("canon", {})
    canon.setdefault("personnages", [])
    canon.setdefault("acquis", [])
    canon.setdefault("apparitions", {})
    for t in _tous_tomes(serie):
        t.setdefault("statut", "en_cours")
    return serie


# ── Épisodes d'écoute (~12 min) : regroupement des chapitres ─────

def _cible_episode_secondes(serie: dict) -> int:
    v = serie.get("cible_episode_secondes")
    return int(v) if isinstance(v, (int, float)) and v > 0 else CIBLE_EPISODE_SECONDES


def _duree_moyenne_chapitre(serie: dict) -> Optional[float]:
    """Durée moyenne (s) des chapitres SONORISÉS, ou None si aucun audio encore."""
    durees = [e["duree"] for e in serie.get("episodes", [])
              if isinstance(e.get("duree"), (int, float)) and e["duree"] > 0]
    return sum(durees) / len(durees) if durees else None


def _chapitres_par_episode(serie: dict) -> int:
    """Combien de chapitres remplissent la cible (~12 min), d'après l'audio réel."""
    moy = _duree_moyenne_chapitre(serie)
    if not moy:
        return CHAPITRES_PAR_EPISODE_DEFAUT
    return max(1, round(_cible_episode_secondes(serie) / moy))


def _est_fin_episode(serie: dict, numero: int) -> bool:
    """Le chapitre `numero` (1-based) clôt-il un épisode ?"""
    par = _chapitres_par_episode(serie)
    anterieurs = sorted((e for e in serie.get("episodes", []) if e.get("n", 0) < numero),
                        key=lambda e: e.get("n", 0))
    depuis = 0
    for ch in anterieurs:
        depuis = 0 if ch.get("fin_episode") else depuis + 1
    return (depuis + 1) >= par


def _decoupage_episodes(serie: dict) -> dict:
    """Regroupe les chapitres en épisodes d'~12 min (vue lisible pour le frontend)."""
    par = _chapitres_par_episode(serie)
    chapitres = sorted(serie.get("episodes", []), key=lambda e: e.get("n", 0))
    episodes, lot = [], []

    def _fermer():
        episodes.append({
            "numero": len(episodes) + 1,
            "chapitres": [e.get("n") for e in lot],
            "duree_reelle": round(sum(e.get("duree") or 0 for e in lot)),
            "tout_sonorise": all(e.get("duree") for e in lot),
            "fin_explicite": bool(lot and lot[-1].get("fin_episode")),
        })

    for ch in chapitres:
        lot.append(ch)
        if ch.get("fin_episode") or len(lot) >= par:
            _fermer()
            lot = []
    if lot:
        _fermer()

    moy = _duree_moyenne_chapitre(serie)
    return {
        "cible_secondes": _cible_episode_secondes(serie),
        "cible_minutes": round(_cible_episode_secondes(serie) / 60),
        "chapitres_par_episode": par,
        "duree_moyenne_chapitre": round(moy) if moy else None,
        "base_estimation": "audio_reel" if moy else "defaut",
        "nb_chapitres": len(chapitres),
        "episodes": episodes,
    }


# Balises son injectées par le Script Doctor — à retirer pour la version « livre ».
_SFX_RE = re.compile(r"\[(?:SFX|AMBIANCE|MUSIQUE)\s*:?[^\]]*\]", re.I)


def _texte_livre(ep: dict) -> str:
    """Texte narratif propre d'un chapitre : sans les balises son [SFX]/[AMBIANCE]/[MUSIQUE]."""
    txt = ep.get("script_brut") or ep.get("script_balise") or ""
    txt = _SFX_RE.sub("", txt)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def _bible_texte(serie: dict) -> str:
    if not serie.get("bible"):
        return "(vide — c'est le tout début)"
    return "\n".join(f"- {k} : {v}" for k, v in serie["bible"].items())


# ── Public cible (âge du lecteur) ────────────────────────────────
CIBLES = {
    "0-3":    "tout-petit (0-3 ans)",
    "4-6":    "enfant de maternelle (4-6 ans)",
    "7-9":    "enfant (7-9 ans)",
    "10-12":  "pré-adolescent (10-12 ans)",
    "13-17":  "adolescent (13-17 ans)",
    "adulte": "public adulte",
}

CIBLE_GUIDE = {
    "0-3":    "Histoire TRÈS courte. Phrases simples et répétitives, vocabulaire de base, ton "
              "doux et rassurant, héros attachants, beaucoup de concret (animaux, couleurs, sons). "
              "Apporte une morale simple et positive. AUCUNE violence, peur, ni tension.",
    "4-6":    "Histoire courte, imaginative et ludique. Vocabulaire simple, phrases claires, une "
              "morale explicite à la fin. Émotions douces, humour gentil, pas de violence.",
    "7-9":    "Aventure rythmée, vocabulaire accessible mais varié, petits enjeux, humour et "
              "valeurs positives (amitié, courage, partage). Suspense léger seulement.",
    "10-12":  "Intrigue plus élaborée, personnages nuancés, enjeux et suspense modérés adaptés à "
              "l'âge. Thèmes émotionnels possibles mais rien de cru ni de violent.",
    "13-17":  "Thèmes plus matures et émotionnels permis, intrigue complexe et ambiguïtés morales, "
              "mais SANS contenu explicite (sexe, gore, drogue détaillée).",
    "adulte": "Public adulte : liberté de ton et de thèmes, intrigue exigeante.",
}

# Registre SEUL (vocabulaire, longueur de phrase, intensité émotionnelle) — à la différence de
# `CIBLE_GUIDE` ci-dessus (destiné à l'ÉCRITURE d'un chapitre neuf), cette table ne contient
# AUCUNE consigne de raccourcissement, de morale ou de censure de contenu : elle sert à
# `_adapter_cible` qui adapte un texte DÉJÀ ÉCRIT à la lecture, sans jamais toucher à
# l'intrigue (S231 revue finale, C2 — injecter `CIBLE_GUIDE` ici contredisait « jamais
# l'histoire » du prompt système).
CIBLE_REGISTRE = {
    "0-3":    "Phrases très courtes et simples, vocabulaire de base concret, rythme lent, "
              "intensité émotionnelle très atténuée.",
    "4-6":    "Phrases courtes et claires, vocabulaire simple, intensité émotionnelle douce.",
    "7-9":    "Vocabulaire accessible mais varié, phrases de longueur modérée, intensité "
              "légère à modérée.",
    "10-12":  "Vocabulaire et longueur de phrase intermédiaires, intensité modérée.",
    "13-17":  "Vocabulaire et syntaxe plus riches, intensité plus soutenue.",
    "adulte": "Registre libre, aucune contrainte de simplification.",
}


def _consigne_cible(serie: dict) -> str:
    """Bloc de consigne à injecter en tête des prompts selon la cible (vide si non définie)."""
    c = serie.get("cible")
    if not c:
        return ""
    label = CIBLES.get(c, c)
    guide = CIBLE_GUIDE.get(c, "")
    return f"PUBLIC CIBLE : {label}. {guide}\nAdapte IMPÉRATIVEMENT le contenu à ce public.\n\n"


# ── Langue (S45) ─────────────────────────────────────────────────
LANGUES = {          # code ISO 639-1 → (nom pour INSTRUIRE le LLM, label NATIF pour l'UI)
    "fr": ("français", "Français"),
    "en": ("anglais (English)", "English"),
    "es": ("espagnol (Español)", "Español"),
    "ar": ("arabe (العربية)", "العربية"),
    "pt": ("portugais (Português)", "Português"),
    "ja": ("japonais (日本語)", "日本語"),
    "zh": ("chinois (中文)", "中文"),
}
LANGUE_DEFAUT = "fr"


def _norm_langue(x) -> str:
    """Ramène une entrée libre à un code supporté ; repli `fr` si inconnu/vide."""
    code = (str(x or "").strip().lower())[:2]
    return code if code in LANGUES else LANGUE_DEFAUT


def _consigne_langue(serie: dict) -> str:
    """Bloc de consigne (langue de RÉDACTION) à injecter en tête des prompts de génération."""
    nom = LANGUES[_norm_langue(serie.get("langue"))][0]
    return (f"LANGUE DE RÉDACTION : {nom}. Rédige absolument TOUT le contenu en {nom}, "
            f"quelle que soit la langue de ces instructions.\n\n")


def _extraire_json(txt: str):
    """Récupère un tableau JSON même s'il est entouré de prose / fences markdown."""
    txt = re.sub(r"```(json)?", "", txt)
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _extraire_obj(txt: str):
    """Récupère un objet JSON {...} même entouré de prose / fences markdown."""
    txt = re.sub(r"```(json)?", "", txt)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def _traduire(textes: list, vers_nom: str) -> tuple:
    """Traduit une liste de répliques en lot via la Gateway gratuite, dans l'ordre.

    Retourne (liste traduite, True) si succès, sinon (liste d'origine, False) — repli
    HONNÊTE : on ne casse jamais la sonorisation, on signale juste que la traduction
    n'a pas eu lieu (Gateway injoignable, JSON illisible, ou nombre de lignes incohérent)."""
    if not textes:
        return textes, True
    paquet = json.dumps([{"i": i, "t": t} for i, t in enumerate(textes)], ensure_ascii=False)
    try:
        brut = await _gateway_answer(
            GW_URL, GW_MODEL,
            "Tu es un traducteur de scripts audio. Tu traduis FIDÈLEMENT en gardant le sens, "
            "le registre et le ton. Tu ne commentes pas, tu n'ajoutes rien, tu ne fusionnes "
            "ni ne supprimes aucune réplique.",
            f"Traduis en {vers_nom} le champ \"t\" de chaque entrée. Réponds UNIQUEMENT un "
            f"tableau JSON [{{\"i\":0,\"t\":\"...\"}}] de MÊME longueur et MÊME ordre.\n\n{paquet}")
        data = _extraire_json(brut) or []
        if len(data) != len(textes):
            return textes, False
        par_i = {int(d.get("i")): (d.get("t") or "") for d in data if "i" in d}
        traduits = [str(par_i.get(i) or textes[i]).strip() or textes[i] for i in range(len(textes))]
        return traduits, True
    except Exception:  # noqa: BLE001
        return textes, False


async def _adapter_cible(texte: str, cible: str, langue: str = "fr") -> tuple:
    """Adapte le REGISTRE (vocabulaire, longueur, intensité) d'un texte à une tranche d'âge —
    JAMAIS l'intrigue. Calquée sur `_traduire` : repli HONNÊTE (texte d'origine, `ok=False`)
    si la Gateway échoue, répond vide, ou si la longueur part trop loin de l'original (garde-
    fou anti-troncature/anti-délire — pas de liste de répliques à recompter ici, juste un
    texte continu, d'où un contrôle par ratio plutôt que par nombre d'entrées).

    `langue` (code ISO, résolu par l'appelant via `serie.get("langue")`) pin la langue de
    SORTIE : sans consigne explicite, le LLM peut répondre en français par défaut même sur un
    texte source dans une autre langue (S231 revue finale, I1)."""
    if not texte or cible not in CIBLE_REGISTRE:
        return texte, True
    label = CIBLES.get(cible, cible)
    registre = CIBLE_REGISTRE[cible]
    nom_langue = LANGUES[_norm_langue(langue)][0]
    try:
        adapte = await _gateway_answer(
            GW_URL, GW_MODEL,
            "Tu adaptes un script audio à un public précis, SANS jamais changer l'histoire, "
            "les personnages, ni les événements. Tu ajustes SEULEMENT le vocabulaire, la "
            "longueur des phrases et l'intensité émotionnelle. Tu préserves EXACTEMENT les "
            "balises [SFX]/[AMBIANCE]/[MUSIQUE] et les didascalies entre parenthèses.",
            f"PUBLIC CIBLE : {label}. {registre}\n\nAdapte ce texte à ce public, en conservant "
            f"scrupuleusement la MÊME histoire, la MÊME longueur d'événements racontés et TOUS "
            f"les événements — n'ajoute, ne coupe et ne moralise RIEN, ajuste UNIQUEMENT le "
            f"vocabulaire, la longueur des phrases et l'intensité émotionnelle. Réponds "
            f"STRICTEMENT dans la même langue que le texte fourni : {nom_langue}.\n\n{texte}")
    except Exception:  # noqa: BLE001
        return texte, False
    adapte = (adapte or "").strip()
    if not adapte:
        return texte, False
    ratio = len(adapte) / max(1, len(texte))
    if ratio < 0.3 or ratio > 3:
        return texte, False
    return adapte, True


# ── Valeurs humaines illustrées par un chapitre (V1 saga familiale) ──
# Liste fixe, choisie par le parent OU suggérée par le Script Doctor. Jamais d'analyse
# comportementale de l'enfant ici — uniquement « quelle valeur ce CHAPITRE illustre-t-il ».
VALEURS = {
    "courage": "Courage", "honnetete": "Honnêteté", "respect": "Respect",
    "empathie": "Empathie", "entraide": "Entraide", "patience": "Patience",
    "perseverance": "Persévérance", "generosite": "Générosité",
    "tolerance": "Tolérance", "curiosite": "Curiosité",
    "responsabilite": "Responsabilité", "confiance": "Confiance",
    "solidarite": "Solidarité", "justice": "Justice", "liberte": "Liberté",
    "gratitude": "Gratitude",
}


async def _suggerer_valeur(texte: str) -> Optional[str]:
    """Suggère UNE valeur humaine illustrée par ce chapitre (Script Doctor) — jamais
    bloquant (même politique que `_traduire`/`_adapter_cible`) : `None` si le LLM échoue,
    répond hors-liste, ou si `texte` est vide. N'écrit rien : l'appelant décide."""
    if not texte:
        return None
    cles = ", ".join(VALEURS.keys())
    try:
        doctor = agent("Script Doctor")
        brut = await _demander(
            doctor,
            "Quelle valeur humaine ce chapitre illustre-t-il le mieux (pas forcément "
            "explicitement — une situation qui la met en jeu suffit) ? Choisis EXACTEMENT "
            f"une clé parmi : {cles}. Réponds UNIQUEMENT en JSON : {{\"valeur\":\"...\"}}.\n\n"
            + texte[:3000])
    except Exception:  # noqa: BLE001
        return None
    data = _extraire_obj(brut) or {}
    valeur = data.get("valeur")
    return valeur if valeur in VALEURS else None


# ── Distribution (personnages structurés, S47) ───────────────────

def _cle_perso(nom: str) -> str:
    """Clé de rapprochement script ⇄ fiche : nom normalisé (casse/espaces)."""
    return re.sub(r"\s+", " ", (nom or "").strip()).upper()


def _distribution_texte(serie: dict) -> str:
    """Bloc DISTRIBUTION injecté dans les prompts d'écriture (vide si aucune fiche)."""
    persos = serie.get("personnages") or []
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
    return ("DISTRIBUTION DE LA SÉRIE (utilise EXACTEMENT ces personnages et ces noms ; "
            "n'en invente pas d'autres sans nécessité) :\n" + "\n".join(lignes) + "\n\n")


# ── Journal de continuité (S50) ──────────────────────────────────
CANON_MAX_PERSOS = 40    # garde-fou taille du contexte
CANON_MAX_ACQUIS = 30


def _personnages_connus(serie: dict) -> list:
    """Noms canoniques établis : fiches de distribution + noms récoltés, dédoublonnés."""
    vus, noms = set(), []
    for source in ([p.get("nom") for p in (serie.get("personnages") or [])],
                   (serie.get("canon") or {}).get("personnages") or []):
        for nom in source:
            cle = _cle_perso(nom)
            if cle and cle not in vus and cle != "NARRATEUR":
                vus.add(cle)
                noms.append(re.sub(r"\s+", " ", str(nom).strip()))
    return noms


def _consigne_personnages(serie: dict) -> str:
    """Bloc « noms canoniques établis » (vide tant qu'aucun nom n'est connu)."""
    noms = _personnages_connus(serie)
    if not noms:
        return ""
    return ("PERSONNAGES DÉJÀ ÉTABLIS (réutilise EXACTEMENT ces noms d'un chapitre à "
            "l'autre ; n'invente un nouveau nom QUE pour un personnage réellement nouveau) :\n"
            + ", ".join(noms) + "\n\n")


def _consigne_acquis(serie: dict) -> str:
    """Bloc « faits déjà acquis » (anti-reboot ; vide tant que rien n'est acquis)."""
    acquis = (serie.get("canon") or {}).get("acquis") or []
    if not acquis:
        return ""
    return ("FAITS DÉJÀ ACQUIS dans l'histoire (ils ont DÉJÀ eu lieu — ne les rejoue PAS, "
            "ne recommence pas l'histoire, ne re-résous pas ces événements ; avance à partir "
            "de là) :\n" + "\n".join(f"- {f}" for f in acquis) + "\n\n")


def _fusion_canon(serie: dict, personnages, acquis) -> None:
    """Fusionne (idempotent, dédoublonné, plafonné) des noms/faits dans le canon.

    `canon.apparitions` (pont Studio↔world-engine) compte le nombre de CHAPITRES
    DISTINCTS où chaque nom a été vu — jamais plus d'une fois par appel, même si le
    script en mentionne le nom plusieurs fois : c'est ce qui rend le seuil de
    récurrence (`SEUIL_RECURRENCE_PONT`) vérifiable objectivement."""
    canon = serie.setdefault("canon", {})
    cps = canon.setdefault("personnages", [])
    apparitions = canon.setdefault("apparitions", {})
    vus = {_cle_perso(n) for n in cps}
    cles_du_chapitre = set()
    for nom in personnages or []:
        cle = _cle_perso(nom)
        if not cle or cle == "NARRATEUR":
            continue
        cles_du_chapitre.add(cle)
        if cle not in vus:
            vus.add(cle)
            cps.append(re.sub(r"\s+", " ", str(nom).strip()))
    for cle in cles_du_chapitre:
        apparitions[cle] = apparitions.get(cle, 0) + 1
    canon["personnages"] = cps[:CANON_MAX_PERSOS]
    canon["apparitions"] = apparitions

    cac = canon.setdefault("acquis", [])
    deja = {re.sub(r"\s+", " ", f.strip().lower()) for f in cac}
    for fait in acquis or []:
        f = re.sub(r"\s+", " ", str(fait).strip())
        if f and f.lower() not in deja:
            deja.add(f.lower())
            cac.append(f)
    canon["acquis"] = cac[-CANON_MAX_ACQUIS:]   # on garde les plus récents


async def _recolter_canon(serie: dict, script: str) -> None:
    """Met à jour le canon depuis le dernier chapitre (1 appel Gateway gratuit).

    Repli HONNÊTE : toute erreur = no-op ; on ne casse jamais la création d'un chapitre."""
    if not (script or "").strip():
        return
    try:
        brut = await _gateway_answer(
            GW_URL, GW_MODEL,
            "Tu extrais la continuité d'un script, sans rien inventer ni interpréter.",
            "À partir de ce chapitre, renvoie UNIQUEMENT un objet JSON :\n"
            '{"personnages": ["NOM", ...], "acquis": ["fait irréversible déjà arrivé", ...]}\n'
            "- personnages : les noms PROPRES des personnages qui parlent ou agissent "
            "(en MAJUSCULES, sans NARRATEUR).\n"
            "- acquis : les événements IRRÉVERSIBLES survenus dans CE chapitre (mort, "
            "lieu atteint, objet détruit/créé, mission accomplie), formulés en une phrase "
            "courte au passé. N'invente rien ; si rien d'irréversible, renvoie [].\n\n"
            + (script or "")[:3500])
        obj = _extraire_obj(brut) or {}
        _fusion_canon(serie, obj.get("personnages"), obj.get("acquis"))
    except Exception:  # noqa: BLE001
        return


# ── Garde-langue (S50) : anglicismes / jargon résiduels ──────────
_JARGON_EN = frozenset({
    # — jargon jeu vidéo / RPG —
    "gameplay", "gamer", "spawn", "respawn", "checkpoint", "loot", "buff", "nerf",
    "quest", "skill", "skills", "boss", "bosses", "level", "levels", "score",
    "highscore", "achievement", "unlock", "unlocked", "cooldown", "mana", "health",
    "damage", "hitbox", "combo", "noob", "newbie", "gameover", "ragequit", "respawning",
    "tutorial", "tutoriel", "boost", "unbalanced", "balanced", "leveling", "grinding",
    # — tech / informatique —
    "bug", "bugs", "debug", "feature", "features", "update", "upgrade", "download",
    "upload", "login", "logout", "password", "username", "settings", "backup",
    "screenshot", "click", "swipe", "scroll", "crash", "reboot", "toggle", "dashboard",
    "framework", "deadline", "feedback", "brainstorm", "background", "foreground",
    "overview", "breakthrough", "mindset", "workflow", "layout", "output", "input",
    "default", "loading", "rendering", "streaming", "timing", "tracking",
    # — narration / mots du rapport —
    "backwards", "forward", "forwards", "forming", "twist", "flashback", "suddenly",
    "feeling", "feelings", "somehow", "somewhere", "something", "someone", "somebody",
    "anybody", "everybody", "nobody", "anything", "everything", "nothing", "everyone",
    "everywhere", "anywhere", "wrong", "right", "indeed", "actually", "basically",
    "literally", "honestly", "seriously", "totally", "definitely", "whatever",
    "anyway", "anyways", "however", "therefore", "meanwhile",
    # — interjections / social —
    "okay", "yeah", "yep", "yup", "nope", "wow", "oops", "ouch", "hey", "please",
    "sorry", "thanks", "thank", "bye", "goodbye", "hello", "dude", "guys", "bro",
    "awesome", "amazing", "cool", "nice", "great", "sure", "yes", "guy", "stuff",
    # — mots de liaison / pronoms anglais (jamais français) —
    "the", "and", "with", "without", "from", "what", "who", "whose", "where", "when",
    "why", "how", "which", "this", "that", "these", "those", "here", "there", "then",
    "than", "them", "they", "their", "your", "you", "yours", "our", "ours", "his",
    "her", "hers", "its", "is", "are", "was", "were", "been", "being", "have", "has",
    "had", "will", "would", "should", "could", "can", "may", "might", "must", "shall",
    "because", "about", "after", "before", "while", "during", "between", "through",
})

# Contractions anglaises : un apostrophe + suffixe anglais → fuite certaine.
_CONTRACTION_EN = re.compile(
    r"\b\w+(?:n't|'re|'ll|'ve|'m|'s)\b|\blet's\b|\bgonna\b|\bwanna\b|\bgotta\b",
    re.IGNORECASE)

# Expressions multi-mots typiquement anglaises (recherchées telles quelles).
_PHRASES_EN = (
    "something is wrong", "what the", "oh my god", "oh my", "by the way", "let's go",
    "come on", "no way", "i don't know", "what is going on", "game over", "boss final",
    "final boss", "level up", "you know", "of course", "all right", "as well",
    "right now", "so far", "kind of", "as soon as", "make sense", "out of",
)


def _anglicismes(texte: str, serie: dict) -> list:
    """Fuites anglophones (lexique + contractions + expressions) dans un script non anglais."""
    if _norm_langue(serie.get("langue")) == "en":
        return []
    txt = texte or ""
    bas = txt.lower()
    trouves, vus = [], set()

    def _ajouter(item):
        if item and item not in vus:
            vus.add(item)
            trouves.append(item)

    # 1) expressions multi-mots (avant les mots isolés, plus parlantes)
    for phrase in _PHRASES_EN:
        if re.search(r"\b" + re.escape(phrase) + r"\b", bas):
            _ajouter(phrase)
    # 2) contractions
    for m in _CONTRACTION_EN.finditer(txt):
        _ajouter(m.group(0).lower())
    # 3) lexique mot à mot
    for mot in re.findall(r"[A-Za-zÀ-ÿ]+", txt):
        m = mot.lower()
        if m in _JARGON_EN:
            _ajouter(m)
    return trouves


# ── Casting (voix figées par personnage) ─────────────────────────

def _assigner_voix(serie: dict, langue: str, pool: list) -> bool:
    """Épingle une voix de `pool` à chaque personnage pour `langue` (idempotent).

    Déterministe (ordre de la distribution) et NON destructif. Retourne True si modifié."""
    if not pool:
        return False
    persos = serie.get("personnages") or []
    prises = [p["voix"][langue] for p in persos
              if isinstance(p.get("voix"), dict) and p["voix"].get(langue) in pool]
    modifie = False
    for i, p in enumerate(persos):
        voix = p.setdefault("voix", {})
        if voix.get(langue) in pool:
            continue
        libre = next((v for v in pool if v not in prises), pool[i % len(pool)])
        voix[langue] = libre
        prises.append(libre)
        modifie = True
    return modifie


def _caster(serie: dict, langue: str, audibles: list, pool: list) -> dict:
    """{NOM_SCRIPT → voix} : voix FIGÉE pour les personnages connus, round-robin sinon."""
    _assigner_voix(serie, langue, pool)
    par_cle = {_cle_perso(p["nom"]): p
               for p in (serie.get("personnages") or []) if p.get("nom")}
    figees = {p["voix"][langue] for p in (serie.get("personnages") or [])
              if isinstance(p.get("voix"), dict) and p["voix"].get(langue) in (pool or [])}
    libres = [v for v in pool if v not in figees] or list(pool)
    casting, extra = {}, 0
    for perso, _texte in audibles:
        if perso in casting:
            continue
        fiche = par_cle.get(_cle_perso(perso))
        if fiche and isinstance(fiche.get("voix"), dict) and fiche["voix"].get(langue):
            casting[perso] = fiche["voix"][langue]
        elif libres:
            casting[perso] = libres[extra % len(libres)]
            extra += 1
        else:
            casting[perso] = ""
    return casting


async def _voix_pool(langue: str = "fr") -> list:
    """Pool de voix de la langue demandée, lu auprès du service hôte (say + ffmpeg)."""
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{VOIX_URL}/sante")
            data = r.json()
            par_langue = data.get("langues") or {}
            pool = par_langue.get(langue) or par_langue.get("fr") or data.get("voix")
            return pool or VOIX_FALLBACK
    except Exception:
        return VOIX_FALLBACK


# ── Pont vers la brique images (5950) ────────────────────────────

def _url_image_absolue(url: str) -> str:
    """Rend une URL d'image affichable par le navigateur (préfixe la brique si relative)."""
    if not url:
        return ""
    return url if url.startswith("http") else f"{IMAGES_PUBLIC.rstrip('/')}{url}"


async def _appeler_images(route: str, payload: dict) -> Optional[dict]:
    """Appelle la brique images ; renvoie son résultat (URL rendue absolue) ou None."""
    try:
        async with httpx.AsyncClient(timeout=200) as c:
            r = await c.post(f"{IMAGES_URL}{route}", json=payload)
            r.raise_for_status()
            data = r.json()
            data["url"] = _url_image_absolue(data.get("url", ""))
            return data
    except Exception:  # noqa: BLE001
        return None


# ── Pont vers la brique video (5970) ─────────────────────────────

def _url_video_absolue(url: str) -> str:
    """Rend une URL de vidéo affichable par le navigateur (préfixe la brique si relative)."""
    if not url:
        return ""
    return url if url.startswith("http") else f"{VIDEO_PUBLIC.rstrip('/')}{url}"


async def _appeler_video(route: str, payload: dict) -> Optional[dict]:
    """Appelle la brique video ; renvoie son résultat (URL rendue absolue) ou None.

    Le rendu vidéo est lent (jobs asynchrones côté fournisseurs) → timeout généreux."""
    try:
        async with httpx.AsyncClient(timeout=600) as c:
            r = await c.post(f"{VIDEO_URL}{route}", json=payload)
            r.raise_for_status()
            data = r.json()
            data["url"] = _url_video_absolue(data.get("url", ""))
            return data
    except Exception:  # noqa: BLE001
        return None


# ── Construction des tâches (prompts) ────────────────────────────

def _recap_episodes(episodes: list) -> str:
    """Contexte de continuité : la liste des épisodes déjà produits + la fin du dernier."""
    if not episodes:
        return ""
    lignes = "\n".join(f"- Épisode {e.get('n')} : {e.get('consigne', '')}" for e in episodes)
    dernier = episodes[-1]
    fin = (dernier.get("script_balise") or dernier.get("script_brut") or "")[-1200:]
    return (
        "Épisodes DÉJÀ produits (pour la continuité, ne les répète pas) :\n" + lignes +
        f"\n\nFin de l'épisode {dernier.get('n')} (enchaîne directement à partir d'ici) :\n{fin}\n\n"
    )


def _consigne_cliffhanger(serie: dict) -> str:
    """Demande au scénariste de fermer un chapitre sur une intrigue de FIN D'ÉPISODE."""
    return (
        "\n\nFIN D'ÉPISODE — INTRIGUE OBLIGATOIRE : ce chapitre CLÔT un épisode d'écoute "
        f"(~{round(_cible_episode_secondes(serie) / 60)} min). Termine-le sur un vrai cliffhanger — "
        "une révélation, un danger imminent, une question laissée ouverte ou un retournement — "
        "qui donne furieusement envie d'écouter la suite. Ne RÉSOUS PAS cette tension ici : "
        "laisse l'auditeur suspendu."
    )


def _tache_scenariste(serie: dict, numero: int, consigne: str, recap: str,
                      finale: bool = False) -> str:
    return (
        f"{_consigne_langue(serie)}{_consigne_cible(serie)}"
        f"Bible de la série « {serie['titre']} » :\n{_bible_texte(serie)}\n\n"
        f"{_distribution_texte(serie)}"
        f"{_consigne_personnages(serie)}"
        f"{_consigne_acquis(serie)}"
        f"{_contexte_volume(serie)}"
        f"{recap}"
        f"Écris le script COURT (1 scène, ~20 répliques) de l'ÉPISODE {numero}, pour : {consigne}.\n"
        "Assure la CONTINUITÉ (mêmes personnages, même fil narratif) sans rejouer les scènes précédentes."
        f"{_consigne_cliffhanger(serie) if finale else ''}"
    )


def _tache_doctor(serie: dict, script: str) -> str:
    """Tâche du Script Doctor : valide, balise, GÈLE — et impose la langue de travail."""
    nom = LANGUES[_norm_langue(serie.get("langue"))][0]
    return (
        "Valide ce script, signale toute incohérence (notamment de continuité : "
        "personnages, faits déjà acquis), puis injecte les balises "
        "[SFX]/[AMBIANCE]/[MUSIQUE] et gèle le texte.\n"
        f"LANGUE : le script gelé doit être ENTIÈREMENT en {nom}. Remplace tout mot ou "
        "expression dans une autre langue (anglicismes, jargon de jeu vidéo type "
        "« boss final », « game over », « tutoriel », « something is wrong ») par son "
        f"équivalent naturel en {nom} ; ne garde en l'état que les noms propres.\n\n"
        "Script :\n" + (script or "")[:3000]
    )


# ── Arbre des choix (helpers) ────────────────────────────────────

async def _noeud(showrunner, serie: dict, chemin: list) -> tuple:
    """Conçoit un nœud : (synopsis, [choixA, choixB]) selon le chemin de choix parcouru."""
    ctx = " → ".join(chemin) if chemin else "(ouverture de la série)"
    tache = (
        f"{_consigne_langue(serie)}{_consigne_cible(serie)}"
        f"Série « {serie['titre']} ». Bible :\n{_bible_texte(serie)}\n\n"
        f"{_distribution_texte(serie)}"
        f"Tu cartographies l'ARBRE NARRATIF interactif. Chemin de choix jusqu'à ce nœud : {ctx}.\n"
        "Conçois CE nœud : un SYNOPSIS court (2-3 phrases, ce qu'il s'y passe) et EXACTEMENT 2 choix "
        "de fin distincts, tentants, qui font diverger l'histoire. "
        'Réponds UNIQUEMENT en JSON : {"synopsis":"...","choix":["...","..."]}.'
    )
    brut = await _demander(showrunner, tache)
    data = _extraire_obj(brut) or {}
    syn = (data.get("synopsis") or brut.strip())[:500]
    choix = data.get("choix") or ["Avancer", "Faire un autre choix"]
    if not isinstance(choix, list) or len(choix) < 2:
        choix = ["Avancer", "Faire un autre choix"]
    return syn, [str(choix[0]), str(choix[1])]


def _trouver_noeud(arbre: dict, noeud_id: str):
    """DFS : retourne (noeud, chemin_de_choix) ou (None, None)."""
    def rec(n, chemin):
        if n.get("id") == noeud_id:
            return n, chemin
        for e in n.get("enfants", []):
            trouve, ch = rec(e["noeud"], chemin + [e["choix"]])
            if trouve:
                return trouve, ch
        return None, None
    return rec(arbre, [])


def _materialiser_chapitre(serie: dict, noeud: dict, chemin: list) -> int:
    """Inscrit la scène d'un nœud comme CHAPITRE dans `episodes` (idempotent)."""
    if noeud.get("episode_n"):
        return noeud["episode_n"]
    numero = len(serie.get("episodes", [])) + 1
    chemin_txt = " → ".join(chemin) if chemin else "Ouverture"
    serie.setdefault("episodes", []).append({
        "n": numero,
        "tome_id": serie.get("tome_actif"),
        "consigne": noeud.get("synopsis", ""),
        "titre": chemin_txt,
        "script_brut": noeud.get("script", ""),
        "source": "arbre",
        "noeud_id": noeud.get("id"),
        "chemin": chemin,
        "le": datetime.now(timezone.utc).isoformat(),
    })
    noeud["episode_n"] = numero
    return numero
