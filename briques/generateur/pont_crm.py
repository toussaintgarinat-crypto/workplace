"""Pont CONSENTI app livrée → CRM du Forge (S24).

Par design (souveraineté), les données d'une app livrée à un client **ne remontent
pas** dans le Forge du cabinet. Ce module ajoute un **pont consenti** : si le client
active le partage, les enregistrements des entités **choisies** (liste blanche)
remontent comme prospects dans le CRM du Forge ; sinon **rien ne sort** (défaut).

Décisions actées (note de prépa `sprint-pont-consenti-crm` + arbitrage 2026-06-08) :
  • **opt-in** : partage = Non par défaut ;
  • périmètre = **liste blanche d'entités** configurable ;
  • à la **révocation / au décrochage** : le pont s'arrête ; la **purge** des données
    déjà remontées se fait **seulement sur demande explicite** (`purger=True`).

Architecture (noyau + briques) — aucun secret ne vit ici :
  • **lecture** de la source via le contrat HTTP de la brique « donnees »
    (`GET /apps/{app_id}/export`) ;
  • **écriture** via la brique « forge » (`POST /crm`), qui détient déjà l'identité
    de service du cabinet (client `forge-service`) et résout le pôle Sales ;
  • **idempotence + purge** : registre local `pont_crm` (rec_id → lead_id) dans la
    base du générateur, pour ne pas dupliquer et pouvoir révoquer.

Best-effort : ne lève jamais ; retourne un rapport détaillé pour journalisation.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

import httpx

DB_PATH = os.getenv("DB_PATH", "/data/apps.db")
DONNEES_URL_INTERNE = os.getenv("DONNEES_URL_INTERNE", "http://host.docker.internal:5500")
FORGE_URL_INTERNE = os.getenv("FORGE_URL_INTERNE", "http://host.docker.internal:5700")

# Pour chaque champ de lead, les clés source candidates (1ʳᵉ valeur non vide gagne).
# Recherche insensible à la casse sur les clés de l'enregistrement.
_MAP = {
    "nom":        ("nom", "name", "client", "contact", "intitule", "titre", "libelle"),
    "email":      ("email", "mail", "courriel", "e-mail"),
    "telephone":  ("telephone", "tel", "phone", "portable", "mobile", "tél"),
    "entreprise": ("entreprise", "societe", "société", "company", "organisation", "raison_sociale"),
    "notes":      ("notes", "note", "commentaire", "description", "remarque", "message"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Registre local (idempotence + purge) ────────────────────────────────────────

def _init_ledger() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pont_crm (
                   app_id    TEXT NOT NULL,
                   entite_id TEXT NOT NULL,
                   rec_id    TEXT NOT NULL,
                   lead_id   TEXT,
                   pousse_le TEXT,
                   PRIMARY KEY (app_id, entite_id, rec_id)
               )"""
        )
        conn.commit()


def _deja_pousses(app_id: str) -> set[tuple[str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT entite_id, rec_id FROM pont_crm WHERE app_id=?", (app_id,)
        ).fetchall()
    return {(r[0], r[1]) for r in rows}


def _enregistrer(app_id: str, entite_id: str, rec_id: str, lead_id: str | None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pont_crm (app_id, entite_id, rec_id, lead_id, pousse_le) "
            "VALUES (?,?,?,?,?)",
            (app_id, entite_id, rec_id, lead_id, _now()),
        )
        conn.commit()


def _leads_de_l_app(app_id: str) -> list[tuple[str, str, str]]:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT entite_id, rec_id, lead_id FROM pont_crm WHERE app_id=?", (app_id,)
        ).fetchall()


def _oublier(app_id: str, entite_id: str, rec_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM pont_crm WHERE app_id=? AND entite_id=? AND rec_id=?",
            (app_id, entite_id, rec_id),
        )
        conn.commit()


_init_ledger()  # garantit la table dès l'import (base partagée avec le générateur)


# ── Mapping enregistrement → lead ────────────────────────────────────────────────

def _vers_lead(rec: dict, app_id: str, entite_id: str) -> dict:
    """Projette un enregistrement métier quelconque sur un lead CRM Forge.

    Heuristique tolérante (clés insensibles à la casse) + traçabilité de provenance
    dans les notes, pour que le cabinet sache d'où vient chaque prospect remonté.
    """
    bas = {str(k).lower(): v for k, v in rec.items() if not str(k).startswith("_")}
    lead: dict = {}
    for champ, candidats in _MAP.items():
        for c in candidats:
            v = bas.get(c)
            if v not in (None, ""):
                lead[champ] = v if isinstance(v, str) else str(v)
                break
    # `nom` est requis côté Forge : repli sur l'entreprise, l'email, puis l'id.
    if not lead.get("nom"):
        lead["nom"] = lead.get("entreprise") or lead.get("email") or f"{entite_id} {rec.get('_id', '')[:8]}"
    # Provenance : marqueur stable (retrouvable même hors registre).
    provenance = f"[pont:{app_id}/{entite_id}]"
    lead["notes"] = (f"{lead.get('notes', '')} {provenance}").strip()
    lead.setdefault("statut", "prospect")
    return lead


# ── Pousser ──────────────────────────────────────────────────────────────────────

def pousser(app_id: str, config: dict) -> dict:
    """Remonte vers le CRM Forge les enregistrements consentis. Best-effort.

    `config` = {"actif": bool, "entites": [entite_id, ...]}.
      • actif=False → ne sort RIEN (comportement par défaut, souveraineté).
      • entites=[]  → aucune entité en liste blanche → rien (opt-in explicite requis).

    Idempotent : un enregistrement déjà remonté (présent au registre) est ignoré.
    Retourne {actif, pousses, ignores, erreurs, total, message}.
    """
    rapport = {"actif": False, "pousses": 0, "ignores": 0, "erreurs": 0,
               "total": 0, "message": ""}
    if not config or not config.get("actif"):
        rapport["message"] = "partage désactivé — rien ne sort (souveraineté)"
        return rapport
    rapport["actif"] = True

    blanche = set(config.get("entites") or [])
    if not blanche:
        rapport["message"] = "aucune entité en liste blanche — rien à remonter"
        return rapport

    # 1) Lecture de la source (brique donnees).
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{DONNEES_URL_INTERNE}/apps/{app_id}/export")
            r.raise_for_status()
            entites = (r.json() or {}).get("entites", {}) or {}
    except Exception as e:
        rapport["message"] = f"lecture donnees échouée : {e}"
        print(f"[pont_crm] export donnees injoignable (app {app_id}) : {e}")
        return rapport

    deja = _deja_pousses(app_id)

    # 2) Écriture vers le CRM (brique forge), enregistrement par enregistrement.
    with httpx.Client(timeout=30) as c:
        for entite_id, recs in entites.items():
            if entite_id not in blanche:
                continue
            for rec in (recs or []):
                if not isinstance(rec, dict):
                    continue
                rapport["total"] += 1
                rec_id = rec.get("_id") or ""
                if (entite_id, rec_id) in deja:
                    rapport["ignores"] += 1
                    continue
                lead = _vers_lead(rec, app_id, entite_id)
                try:
                    rp = c.post(f"{FORGE_URL_INTERNE}/crm", json=lead)
                    rp.raise_for_status()
                    lead_id = (rp.json() or {}).get("id")
                    _enregistrer(app_id, entite_id, rec_id, lead_id)
                    rapport["pousses"] += 1
                except Exception as e:
                    rapport["erreurs"] += 1
                    print(f"[pont_crm] POST /crm échoué (app {app_id} {entite_id}/{rec_id}) : {e}")

    rapport["message"] = (
        f"{rapport['pousses']} prospect(s) remonté(s), {rapport['ignores']} déjà présent(s)"
        + (f", {rapport['erreurs']} erreur(s)" if rapport["erreurs"] else "")
    )
    return rapport


# ── Révoquer (arrêt + purge optionnelle) ─────────────────────────────────────────

def revoquer(app_id: str, purger: bool = False) -> dict:
    """Arrête le pont pour une app. Best-effort, ne lève jamais.

    Le pont s'arrête simplement en désactivant le consentement côté appelant ; ici on
    gère l'effet **purge** (décision : sur demande explicite uniquement) : on supprime
    dans le CRM Forge les leads déjà remontés (via leur `lead_id` au registre) et on
    nettoie le registre. Sans `purger`, le registre est conservé tel quel (les données
    restent côté cabinet, mais aucune nouvelle remontée n'aura lieu).

    Retourne {purge, supprimes, erreurs, restants, message}.
    """
    rapport = {"purge": purger, "supprimes": 0, "erreurs": 0, "restants": 0, "message": ""}
    lignes = _leads_de_l_app(app_id)

    if not purger:
        rapport["restants"] = len(lignes)
        rapport["message"] = "pont arrêté — données déjà remontées conservées (pas de purge demandée)"
        return rapport

    with httpx.Client(timeout=30) as c:
        for entite_id, rec_id, lead_id in lignes:
            if not lead_id:
                _oublier(app_id, entite_id, rec_id)
                continue
            try:
                rp = c.delete(f"{FORGE_URL_INTERNE}/crm/{lead_id}")
                rp.raise_for_status()
                _oublier(app_id, entite_id, rec_id)
                rapport["supprimes"] += 1
            except Exception as e:
                rapport["erreurs"] += 1
                print(f"[pont_crm] DELETE /crm/{lead_id} échoué (app {app_id}) : {e}")

    rapport["restants"] = len(_leads_de_l_app(app_id))
    rapport["message"] = (
        f"{rapport['supprimes']} prospect(s) purgé(s) du CRM"
        + (f", {rapport['erreurs']} erreur(s)" if rapport["erreurs"] else "")
    )
    return rapport
