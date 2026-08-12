"""Mappeurs best-effort post-sync (S230) : transforment les données déjà synchronisées
(cache DuckDB, relu via `pont.executer(action="extraire")`) vers les consommateurs métier
du pipeline audit → conception de solutions — Forge (CRM, dossier client) et audit (ROI).

Liste blanche explicite, pas de détection automatique du type de connecteur (décision
actée au cadrage S230) : seuls les connecteurs listés ci-dessous déclenchent un mappage.
Tout le reste (source-github, source-faker, futurs connecteurs non métiers) n'est jamais
mappé — `dispatcher.py`-style, mais gardé simple dans ce seul module vu la taille du
sprint (deux mappeurs).

Erreurs : chaque mappeur LÈVE `MappingEchoue` plutôt que d'avaler l'erreur — c'est le
dispatcher (`main.py::_syncer`, Task 10) qui l'attrape et journalise `mapping_echoue`
via `stockage.enregistrer_mapping`, jamais ce module. Garde le mappeur testable en
isolation (une levée = un cas de test), et le point d'attrape unique (Task 10 est le SEUL
appelant en production).
"""
from __future__ import annotations

import os

import httpx

import pont
import stockage

FORGE_URL = os.getenv("FORGE_URL", "http://host.docker.internal:5700").rstrip("/")
FORGE_KEY = os.getenv("FORGE_KEY", "")
AUDIT_URL = os.getenv("AUDIT_URL", "http://host.docker.internal:5300").rstrip("/")

POLES_VALIDES = {"commercial", "production", "administratif"}

# Connecteurs PyAirbyte à authentification API-key simple (pas d'OAuth à redirection,
# hors périmètre S230). Le nom exact doit correspondre au champ `connecteur` d'une
# `sources` (S214) — vérifié disponible sur PyPI au moment du cadrage S230.
CONNECTEURS_CRM = {"source-hubspot"}
CONNECTEURS_COMPTA = {"source-harvest"}


class MappingEchoue(RuntimeError):
    """Un mappeur n'a pas pu transformer/pousser les données déjà synchronisées.

    Distinct d'un échec de SYNC (`pont.PontIndisponible`, réseau tiers en panne) : les
    données brutes sont bien dans le cache DuckDB, seul le mappage a échoué — rejouable
    sans retransférer (cf. `enregistrer_mapping`, Task 6)."""


def _entetes() -> dict:
    return {"X-API-Key": FORGE_KEY} if FORGE_KEY else {}


async def _extraire(connecteur: str, source_id: int, schema: str, flux: str) -> list[dict]:
    reponse = await pont.executer(
        {"action": "extraire", "connecteur": connecteur, "flux_extrait": flux,
         "schema": schema, "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")},
        timeout=pont.TIMEOUT_COURT)
    if not reponse.get("ok"):
        raise MappingEchoue(f"extraction du flux « {flux} » : {reponse.get('erreur')}")
    return reponse["lignes"]


# ── CRM (HubSpot) ─────────────────────────────────────────────────────────────

def _contact_vers_prospect(contact: dict) -> dict:
    p = contact.get("properties") or {}
    prenom, nom_famille = (p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()
    nom = f"{prenom} {nom_famille}".strip() or p.get("company") or f"Contact {contact.get('id')}"
    charge = {"nom": nom, "entreprise": p.get("company"), "email": p.get("email"),
             "telephone": p.get("phone"), "notes": "Importé depuis connecteurs (HubSpot, contact)"}
    return {k: v for k, v in charge.items() if v}


def _deal_vers_prospect(deal: dict) -> dict:
    p = deal.get("properties") or {}
    nom_deal = p.get("dealname") or f"Deal {deal.get('id')}"
    notes = f"Importé depuis connecteurs (HubSpot, deal « {nom_deal} »)"
    if p.get("amount"):
        notes += f" — montant {p['amount']}"
    return {"nom": nom_deal, "notes": notes}


async def _mapper_crm(tenant: str, source_id: int, venture_id: str, schema: str) -> None:
    connecteur = "source-hubspot"  # seul connecteur CRM du périmètre S230
    contacts = await _extraire(connecteur, source_id, schema, "contacts")
    deals = await _extraire(connecteur, source_id, schema, "deals")
    prospects = [_contact_vers_prospect(c) for c in contacts] + \
                [_deal_vers_prospect(d) for d in deals]
    if not prospects:
        # Rien de neuf ce tour (sync incrémentale calme — HubSpot ne renvoie que le
        # delta). Ne RIEN appeler : ni lead factice dans le CRM pour satisfaire la
        # validation « liste non vide » de crm/import-lot, ni écrasement du compteur
        # `clients.nb` avec un delta de zéro (cf. commentaire plus bas sur le cumul).
        return

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{FORGE_URL}/crm/import-lot",
                              json={"prospects": prospects, "venture_id": venture_id},
                              headers=_entetes())
        r.raise_for_status()

        # Fusion non destructive de profil_entreprise (motif _fusionner_qualitatif,
        # S227/S228) + comptage CUMULATIF : une sync incrémentale ne rapporte qu'un
        # DELTA de contacts/deals, jamais le total connu chez le tiers — écraser
        # `clients.nb` avec ce delta ferait régresser le profil à chaque sync calme.
        # On ajoute donc au compteur déjà persisté plutôt que de le remplacer. Fenêtre
        # de course acceptée (best-effort, cadence horloge au pire quotidienne).
        rv = await client.get(f"{FORGE_URL}/ventures/{venture_id}", headers=_entetes())
        rv.raise_for_status()
        profil = (rv.json() or {}).get("profilEntreprise") or {}
        nb_existant = (profil.get("clients") or {}).get("nb", 0)
        profil = {**profil, "clients": {"nb": nb_existant + len(prospects),
                                        "exemples": [p["nom"] for p in prospects[:5]]}}
        rp = await client.patch(f"{FORGE_URL}/ventures/{venture_id}",
                                json={"profilEntreprise": profil}, headers=_entetes())
        rp.raise_for_status()


# ── Compta (Harvest) ─────────────────────────────────────────────────────────

async def _mapper_compta(tenant: str, source_id: int, venture_id: str, schema: str) -> None:
    connecteur, config, _flux = stockage.config_de(tenant, source_id)
    mapping_poles: dict[str, str] = (config or {}).get("mapping_poles") or {}
    entries = await _extraire(connecteur, source_id, schema, "time_entries")

    # Agrégation pondérée par pôle : cout_horaire[pole] = Σ(heures·taux) / Σ(heures),
    # sur les seules entrées dont le projet OU la tâche est dans mapping_poles ET qui
    # portent un taux exploitable. Un pôle sans entrée mappable est absent du dict —
    # `chiffrage.py` (S229) le traite alors comme `hypothese_llm`, jamais bloquant.
    ponderation: dict[str, list[tuple[float, float]]] = {}
    for entree in entries:
        projet = (entree.get("project") or {}).get("name")
        tache = (entree.get("task") or {}).get("name")
        pole = mapping_poles.get(projet) or mapping_poles.get(tache)
        if pole not in POLES_VALIDES:
            continue
        heures = entree.get("hours")
        taux = entree.get("billable_rate") if entree.get("billable_rate") is not None \
            else entree.get("cost_rate")
        if not heures or taux is None:
            continue
        ponderation.setdefault(pole, []).append((float(heures), float(taux)))

    cout_horaire = {}
    for pole, paires in ponderation.items():
        total_heures = sum(h for h, _ in paires)
        if total_heures:
            cout_horaire[pole] = sum(h * t for h, t in paires) / total_heures

    async with httpx.AsyncClient(timeout=15) as client:
        rv = await client.get(f"{FORGE_URL}/ventures/{venture_id}", headers=_entetes())
        rv.raise_for_status()
        audit_id = (rv.json() or {}).get("auditId")
        if not audit_id:
            raise MappingEchoue(f"venture {venture_id} sans audit_id — pas de dossier "
                                f"audit à chiffrer")

        r = await client.post(f"{AUDIT_URL}/audits/{audit_id}/chiffrer",
                              json={"cout_horaire": cout_horaire})
        r.raise_for_status()
