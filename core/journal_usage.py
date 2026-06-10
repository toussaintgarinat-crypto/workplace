"""Journal des appels LLM + garde-fou budgétaire (Sprint S138, chantier 0).

Workplace n'a pas de base SQL dans le Cœur (la mémoire est une brique séparée) :
on tient donc le suivi des coûts dans un **journal JSONL** append-only, à l'image
du reste de `core/` qui persiste en fichiers sous `/data`. Une ligne = un appel
LLM, avec ses tokens, son coût et le modèle réellement utilisé.

Ce module est l'équivalent « léger » du governor de workspace (budget jour/mois,
seuil d'alerte 80 %, blocage 95 %), sans table ni migration.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_PATH = Path(os.getenv("USAGE_LLM_PATH", "/data/usage_llm.jsonl"))

# Budgets en USD. 0 = illimité (comportement par défaut, aucune surprise).
BUDGET_JOUR = float(os.getenv("LLM_BUDGET_JOUR_USD", "0") or 0)
BUDGET_MOIS = float(os.getenv("LLM_BUDGET_MOIS_USD", "0") or 0)
SEUIL_ALERTE = 0.80   # 80 % du budget → on prévient
SEUIL_BLOCAGE = 0.95  # 95 % du budget → on bloque les appels payants

_verrou = threading.Lock()


def enregistrer(*, modele: str | None, etiquette: str, tokens_in: int,
                tokens_out: int, cout_usd: float, cache_hit: bool = False,
                trimmed_tokens: int = 0, routed_to: str | None = None,
                complexite: str | None = None, erreur: str | None = None) -> None:
    """Ajoute une ligne au journal. Ne lève jamais : journaliser ne doit pas
    casser l'appel métier (au pire on perd une ligne de stat)."""
    ligne = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modele": modele,
        "etiquette": etiquette,            # chat | classement | test | …
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "cout_usd": round(float(cout_usd or 0), 6),
        "cache_hit": bool(cache_hit),      # [S138-2] cache sémantique (chantier 2)
        "trimmed_tokens": int(trimmed_tokens or 0),
        "routed_to": routed_to,            # [S138-1] modèle économe si rétrogradé
        "complexite": complexite,
        "erreur": erreur,
    }
    try:
        with _verrou:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with JOURNAL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:  # disque plein, droits… on log et on continue
        logger.warning("Journal usage non écrit : %s", e)


def _lignes() -> list[dict]:
    """Lit le journal de façon tolérante (ignore les lignes corrompues)."""
    if not JOURNAL_PATH.exists():
        return []
    out = []
    try:
        with JOURNAL_PATH.open(encoding="utf-8") as f:
            for brute in f:
                brute = brute.strip()
                if not brute:
                    continue
                try:
                    out.append(json.loads(brute))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("Journal usage illisible : %s", e)
    return out


def _agreger(lignes: list[dict]) -> dict:
    return {
        "appels": len(lignes),
        "tokens_in": sum(l.get("tokens_in", 0) for l in lignes),
        "tokens_out": sum(l.get("tokens_out", 0) for l in lignes),
        "cout_usd": round(sum(l.get("cout_usd", 0) for l in lignes), 4),
        "cache_hits": sum(1 for l in lignes if l.get("cache_hit")),
        "tokens_economises_trim": sum(l.get("trimmed_tokens", 0) for l in lignes),
        "appels_retrogrades": sum(1 for l in lignes if l.get("routed_to")),
    }


def agregat_jour(jour: str) -> dict:
    """Agrégats d'usage LLM pour une date donnée `AAAA-MM-JJ` (préfixe `ts`, UTC).

    Sert le briefing quotidien (S30) qui demande le coût « de la veille » ; ne
    dépend pas du jour courant, contrairement à `resume()`."""
    lignes = [l for l in _lignes() if (l.get("ts") or "").startswith(jour)]
    return _agreger(lignes)


def resume() -> dict:
    """Agrégats jour courant / mois courant / total + détail des budgets."""
    lignes = _lignes()
    aujourdhui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ce_mois = datetime.now(timezone.utc).strftime("%Y-%m")
    jour = [l for l in lignes if (l.get("ts") or "").startswith(aujourdhui)]
    mois = [l for l in lignes if (l.get("ts") or "").startswith(ce_mois)]
    return {
        "jour": _agreger(jour),
        "mois": _agreger(mois),
        "total": _agreger(lignes),
        "budget": budget_etat(),
    }


def budget_etat() -> dict:
    """État du budget : dépenses vs plafonds, statut ok|alerte|bloque par période."""
    lignes = _lignes()
    aujourdhui = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ce_mois = datetime.now(timezone.utc).strftime("%Y-%m")
    depense_jour = sum(l.get("cout_usd", 0) for l in lignes
                       if (l.get("ts") or "").startswith(aujourdhui))
    depense_mois = sum(l.get("cout_usd", 0) for l in lignes
                       if (l.get("ts") or "").startswith(ce_mois))

    def statut(depense: float, budget: float) -> str:
        if budget <= 0:
            return "illimite"
        if depense >= budget * SEUIL_BLOCAGE:
            return "bloque"
        if depense >= budget * SEUIL_ALERTE:
            return "alerte"
        return "ok"

    return {
        "jour": {"depense_usd": round(depense_jour, 4), "budget_usd": BUDGET_JOUR,
                 "statut": statut(depense_jour, BUDGET_JOUR)},
        "mois": {"depense_usd": round(depense_mois, 4), "budget_usd": BUDGET_MOIS,
                 "statut": statut(depense_mois, BUDGET_MOIS)},
    }


def peut_appeler_payant() -> bool:
    """False si le budget jour OU mois est en blocage (≥ 95 %). Les modèles
    gratuits restent toujours autorisés (cf. `llm_pipeline`)."""
    etat = budget_etat()
    return etat["jour"]["statut"] != "bloque" and etat["mois"]["statut"] != "bloque"
