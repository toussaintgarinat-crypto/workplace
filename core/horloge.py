"""Horloge — planificateur de tâches périodiques (Sprint S29).

Fidèle au modèle **noyau + briques** : le Cœur ne code en dur AUCUNE tâche métier.
Chaque brique **déclare** ses tâches périodiques dans son `manifest.json` (champ
`taches` — le contrat : *quoi* exécuter, *quand*, *idempotence*). L'horloge les
découvre via le registre et les déclenche quand elles sont dues, en appelant le
contrat HTTP de la brique (même résolution d'URL que l'orchestrateur).

Répartition des responsabilités :
  • l'**idempotence métier** reste à la brique (relances anti-doublon par
    facture×niveau S22, pull Google Agenda idempotent S27) ;
  • l'**horloge** garantit seulement qu'une tâche n'est pas redéclenchée avant que
    sa cadence (`cadence_heures`) soit écoulée, et journalise chaque exécution.

Reprend le motif de `core/proactif.py` : une simple boucle asyncio + un journal
SQLite side-car, SANS Redis ni broker externe. Observable : chaque run est tracé
(statut + résultat tronqué) et consultable via `GET /horloge/taches`.

Contrat d'une tâche (dans `manifest.json`) :
    "taches": [
      {
        "nom": "relances-impayes",          # identifiant dans la brique
        "description": "…",                  # lisible
        "methode": "POST",                   # verbe HTTP (défaut POST)
        "chemin": "/relances/executer",      # chemin relatif à la base de la brique
        "cadence_heures": 24,                # période minimale entre deux exécutions
        "idempotent": true,                  # documentaire : la brique dédoublonne
        "entetes": {"X-User-Id": "perso"},   # en-têtes statiques (optionnel, non secret)
        "entete_token_env": "CALENDAR_SERVICE_TOKEN",  # nom d'env → Authorization: Bearer (optionnel)
        "tolere_echec": true                 # un 4xx/5xx n'est pas une anomalie (ex. Google non connecté)
      }
    ]
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import httpx

import orchestrateur

logger = logging.getLogger(__name__)

DB = os.getenv("HORLOGE_DB", "/data/horloge.db")
INTERVALLE = int(os.getenv("HORLOGE_INTERVALLE", "900"))  # tick : toutes les 15 min
CADENCE_DEFAUT_H = 24.0


# ── Journal SQLite (état par tâche) ──────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS horloge_journal (
                brique             TEXT NOT NULL,
                tache              TEXT NOT NULL,
                derniere_execution TEXT,
                dernier_statut     TEXT,
                dernier_resultat   TEXT,
                nb_executions      INTEGER DEFAULT 0,
                PRIMARY KEY (brique, tache)
            )
        """)


def _etat(brique: str, tache: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM horloge_journal WHERE brique = ? AND tache = ?",
            (brique, tache),
        ).fetchone()
    return dict(row) if row else None


def _enregistrer(brique: str, tache: str, *, statut: str, resultat: str,
                 quand: datetime) -> None:
    """Met à jour le journal : avance l'horloge de la tâche (succès OU échec) pour
    respecter la cadence, et trace le dernier statut/résultat (tronqué)."""
    with _conn() as c:
        c.execute(
            """
            INSERT INTO horloge_journal
                (brique, tache, derniere_execution, dernier_statut, dernier_resultat, nb_executions)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(brique, tache) DO UPDATE SET
                derniere_execution = excluded.derniere_execution,
                dernier_statut     = excluded.dernier_statut,
                dernier_resultat   = excluded.dernier_resultat,
                nb_executions      = horloge_journal.nb_executions + 1
            """,
            (brique, tache, quand.isoformat(), statut, resultat[:500]),
        )


# ── Cadence (pure, testable sans DB ni réseau) ───────────────────────────────

def tache_due(derniere_iso: str | None, cadence_heures: float,
              maintenant: datetime) -> bool:
    """Une tâche est due si elle n'a jamais tourné, ou si sa cadence est écoulée.

    Pure : aucune I/O. Combinée à `_enregistrer` (qui avance l'horloge même en cas
    d'échec), elle évite de marteler une brique en panne avant la prochaine période.
    """
    if not derniere_iso:
        return True
    try:
        derniere = datetime.fromisoformat(derniere_iso)
    except (ValueError, TypeError):
        return True  # journal illisible → on relance
    return maintenant - derniere >= timedelta(hours=cadence_heures)


# ── Collecte des tâches déclarées dans les manifests ─────────────────────────

_CHAMPS_REQUIS = ("nom", "chemin")


def collecter_taches(registre) -> list[dict]:
    """Découvre toutes les tâches déclarées par les briques (champ manifest `taches`).

    Normalise (méthode/cadence par défaut), valide les champs requis, et ignore —
    en le signalant — toute déclaration incomplète plutôt que de planter la boucle.
    """
    taches: list[dict] = []
    for nom_brique, manifest in registre.briques.items():
        for decl in manifest.get("taches", []) or []:
            if not all(decl.get(c) for c in _CHAMPS_REQUIS):
                logger.warning("Horloge : tâche incomplète ignorée dans '%s' : %r",
                               nom_brique, decl)
                continue
            taches.append({
                "brique": nom_brique,
                "nom": decl["nom"],
                "description": decl.get("description", ""),
                "methode": (decl.get("methode") or "POST").upper(),
                "chemin": decl["chemin"],
                "cadence_heures": float(decl.get("cadence_heures") or CADENCE_DEFAUT_H),
                "idempotent": bool(decl.get("idempotent", False)),
                "entetes": dict(decl.get("entetes") or {}),
                "entete_token_env": decl.get("entete_token_env"),
                "tolere_echec": bool(decl.get("tolere_echec", False)),
            })
    return taches


def _entetes(tache: dict) -> dict:
    """En-têtes effectifs : ceux du manifest + un éventuel Bearer dont le NOM d'env
    est déclaré (le secret reste en variable d'environnement, jamais dans le manifest)."""
    entetes = dict(tache.get("entetes") or {})
    env = tache.get("entete_token_env")
    if env and os.environ.get(env):
        entetes["Authorization"] = f"Bearer {os.environ[env]}"
    return entetes


# ── Exécution ────────────────────────────────────────────────────────────────

async def _executer(client: httpx.AsyncClient, tache: dict, quand: datetime) -> dict:
    """Déclenche une tâche (appel HTTP du contrat de la brique) et la journalise.

    Ne lève jamais : un échec est tracé (statut `echec`/`erreur`) et l'horloge est
    tout de même avancée pour respecter la cadence. Renvoie un résumé pour le rapport.
    """
    brique, nom = tache["brique"], tache["nom"]
    try:
        base = orchestrateur._brique_base(registre=tache["_registre"], nom=brique)
    except RuntimeError as e:
        _enregistrer(brique, nom, statut="indisponible", resultat=str(e), quand=quand)
        return {"brique": brique, "tache": nom, "statut": "indisponible", "detail": str(e)}

    url = f"{base}{tache['chemin']}"
    try:
        r = await client.request(tache["methode"], url, headers=_entetes(tache), timeout=120)
    except httpx.HTTPError as e:
        _enregistrer(brique, nom, statut="injoignable", resultat=str(e), quand=quand)
        return {"brique": brique, "tache": nom, "statut": "injoignable", "detail": str(e)}

    corps = r.text[:500]
    if r.status_code >= 400:
        # `tolere_echec` : attendu (ex. Google non connecté) → statut `ignore`, pas une alarme.
        statut = "ignore" if tache.get("tolere_echec") else "echec"
        niveau = logger.info if tache.get("tolere_echec") else logger.warning
        niveau("Horloge : %s/%s → HTTP %s : %s", brique, nom, r.status_code, corps)
        _enregistrer(brique, nom, statut=statut, resultat=f"HTTP {r.status_code} : {corps}", quand=quand)
        return {"brique": brique, "tache": nom, "statut": statut, "code_http": r.status_code}

    _enregistrer(brique, nom, statut="ok", resultat=corps, quand=quand)
    logger.info("Horloge : %s/%s exécutée ✓", brique, nom)
    return {"brique": brique, "tache": nom, "statut": "ok", "code_http": r.status_code}


async def run_due(registre, *, maintenant: datetime | None = None, forcer: bool = False,
                  filtre_brique: str | None = None, filtre_tache: str | None = None) -> dict:
    """Exécute les tâches dues (ou toutes si `forcer`). Filtrable sur une seule tâche.

    Renvoie un rapport : ce qui a été exécuté, ce qui a été sauté (pas encore dû).
    """
    init_db()
    maintenant = maintenant or datetime.utcnow()
    toutes = collecter_taches(registre)
    a_lancer, sautees, rapport = [], [], []

    for t in toutes:
        if filtre_brique and t["brique"] != filtre_brique:
            continue
        if filtre_tache and t["nom"] != filtre_tache:
            continue
        etat = _etat(t["brique"], t["nom"])
        derniere = etat.get("derniere_execution") if etat else None
        if forcer or tache_due(derniere, t["cadence_heures"], maintenant):
            t["_registre"] = registre
            a_lancer.append(t)
        else:
            sautees.append({"brique": t["brique"], "tache": t["nom"],
                            "derniere_execution": derniere, "cadence_heures": t["cadence_heures"]})

    if a_lancer:
        async with httpx.AsyncClient() as client:
            rapport = [await _executer(client, t, maintenant) for t in a_lancer]

    return {
        "executees": rapport,
        "nb_executees": len(rapport),
        "sautees": sautees,
        "nb_taches_declarees": len(toutes),
    }


def lister_etat(registre) -> list[dict]:
    """État de toutes les tâches déclarées : cadence, dernière exécution, statut,
    et prochaine échéance — pour `GET /horloge/taches` et le briefing (S30)."""
    init_db()
    out = []
    for t in collecter_taches(registre):
        etat = _etat(t["brique"], t["nom"]) or {}
        derniere = etat.get("derniere_execution")
        prochaine = None
        if derniere:
            try:
                prochaine = (datetime.fromisoformat(derniere)
                             + timedelta(hours=t["cadence_heures"])).isoformat()
            except (ValueError, TypeError):
                prochaine = None
        out.append({
            "brique": t["brique"],
            "nom": t["nom"],
            "description": t["description"],
            "methode": t["methode"],
            "chemin": t["chemin"],
            "cadence_heures": t["cadence_heures"],
            "idempotent": t["idempotent"],
            "derniere_execution": derniere,
            "dernier_statut": etat.get("dernier_statut"),
            "nb_executions": etat.get("nb_executions", 0),
            "prochaine_echeance": prochaine,
        })
    return out


# ── Boucle de fond (démarrée dans le lifespan du Cœur) ───────────────────────

async def boucle(registre) -> None:
    init_db()
    await asyncio.sleep(30)  # laisser les briques démarrer
    while True:
        try:
            rapport = await run_due(registre)
            if rapport["nb_executees"]:
                logger.info("Horloge : %d tâche(s) exécutée(s)", rapport["nb_executees"])
        except Exception as ex:  # noqa: BLE001
            logger.warning("Horloge boucle : %s", ex)
        await asyncio.sleep(INTERVALLE)
