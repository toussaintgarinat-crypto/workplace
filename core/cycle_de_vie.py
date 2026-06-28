"""Cycle de vie des entreprises (Sprint S6).

Une entreprise livrée a son état éparpillé dans plusieurs briques : documents
(ETL), audit (Audit), app générée + HTML + refs Oria (Générateur), enregistrements
(Données). Ce module permet de :

  • DÉCROCHER : rassembler tout cet état dans UN dossier portable (`dossier.json`)
    posé sur le disque, puis RETIRER l'entreprise des bases centrales → la solution
    principale reste propre, l'entreprise est « mise de côté ».

  • REPRENDRE : réinjecter le dossier dans les briques pour la remodifier ; on peut
    ensuite la re-décrocher. Aller-retour sans perte.

Le Cœur ne réimplémente aucune logique métier : il appelle les contrats HTTP
export/import de chaque brique (modèle « noyau + briques »).
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

import contexte_tenant
import orchestrateur

# Dossier où sont écrits les dossiers portables (monté sur l'hôte : apps_exportees/).
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/export")
FORMAT = "workplace-dossier-v1"


class EchecCycle(Exception):
    """Erreur pendant un décrochage/reprise (brique injoignable, etc.)."""


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(nom: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (nom or "entreprise").lower()).strip("-")
    return s or "entreprise"


def _bases(registre) -> dict:
    """URLs de base des briques métier impliquées dans le cycle de vie."""
    try:
        return {
            "etl": orchestrateur._brique_base(registre, "etl"),
            "audit": orchestrateur._brique_base(registre, "audit"),
            "generateur": orchestrateur._brique_base(registre, "generateur"),
            "donnees": orchestrateur._brique_base(registre, "donnees"),
        }
    except RuntimeError as e:
        raise EchecCycle(str(e))


def _lisezmoi(dossier: dict) -> str:
    nb_docs = len(dossier.get("documents") or [])
    nb_rec = sum(len(v) for v in (dossier.get("donnees") or {}).values())
    app = dossier.get("app") or {}
    return (
        f"DOSSIER D'ENTREPRISE PORTABLE — Workplace (format {FORMAT})\n"
        f"Entreprise : {dossier.get('nom_entreprise')}\n"
        f"Décroché le : {dossier.get('date_decrochage')}\n\n"
        "CONTENU\n"
        "-------\n"
        f"• dossier.json : tout l'état (documents, audit, app, données)\n"
        f"• app.html     : l'application générée (consultable hors-ligne)\n\n"
        f"Documents : {nb_docs}   ·   Données : {nb_rec} enregistrement(s)   ·   "
        f"Mode : {app.get('mode', 'autonome')}\n\n"
        "REPRENDRE CETTE ENTREPRISE\n"
        "--------------------------\n"
        "Depuis le Cœur Workplace, onglet « Usine à apps », carte « De côté » →\n"
        "bouton « Reprendre » : l'entreprise est réinjectée dans la solution pour\n"
        "être modifiée, puis vous pourrez la re-décrocher.\n"
    )


# ── DÉCROCHER ────────────────────────────────────────────────────────────────

async def decrocher(registre, livraison_id: str) -> dict:
    liv = orchestrateur.lire_livraison(livraison_id)
    if not liv:
        raise ValueError("Livraison introuvable")
    if liv.get("statut") == "decrochee":
        raise ValueError("Entreprise déjà décrochée")
    if liv.get("statut") == "en_cours":
        raise ValueError("Livraison en cours — attendez qu'elle se termine")

    bases = _bases(registre)
    doc_ids = liv.get("doc_ids") or []
    audit_id = liv.get("audit_id")
    app_id = liv.get("app_id")

    dossier = {
        "format": FORMAT,
        "nom_entreprise": liv.get("nom_entreprise"),
        "date_decrochage": _maintenant(),
        "livraison": {
            "mode": liv.get("mode"),
            "messagerie": liv.get("messagerie"),
            "packager": liv.get("packager"),
            "date_creation": liv.get("date_creation"),
        },
        "documents": [],
        "audit": None,
        "app": None,
        "donnees": {},
    }

    # 1) Collecte (lecture seule) auprès des briques.
    async with httpx.AsyncClient(timeout=60) as client:
        for did in doc_ids:
            try:
                r = await client.get(f"{bases['etl']}/documents/{did}")
                if r.status_code < 400:
                    dossier["documents"].append(r.json())
            except httpx.HTTPError as e:
                raise EchecCycle(f"ETL injoignable pour le document {did} : {e}")

        if audit_id:
            try:
                r = await client.get(f"{bases['audit']}/audits/{audit_id}")
                if r.status_code < 400:
                    dossier["audit"] = r.json()
            except httpx.HTTPError as e:
                raise EchecCycle(f"Audit injoignable : {e}")

        if app_id:
            try:
                r = await client.get(f"{bases['generateur']}/apps/{app_id}/export")
                if r.status_code < 400:
                    dossier["app"] = r.json()
                r = await client.get(f"{bases['donnees']}/apps/{app_id}/export")
                if r.status_code < 400:
                    dossier["donnees"] = r.json().get("entites", {})
            except httpx.HTTPError as e:
                raise EchecCycle(f"Générateur/Données injoignable : {e}")

    # 2) Écriture du dossier portable sur disque (avant toute suppression).
    base = Path(EXPORT_DIR) / f"{_slug(liv.get('nom_entreprise'))}-dossier"
    base.mkdir(parents=True, exist_ok=True)
    chemin = base / "dossier.json"
    chemin.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
    if (dossier["app"] or {}).get("html"):
        (base / "app.html").write_text(dossier["app"]["html"], encoding="utf-8")
    (base / "LISEZMOI.txt").write_text(_lisezmoi(dossier), encoding="utf-8")

    # 3) Retrait des bases centrales (la solution principale est libérée).
    #    Le dossier portable est désormais la seule source de cette entreprise.
    async with httpx.AsyncClient(timeout=60) as client:
        for did in doc_ids:
            try:
                await client.delete(f"{bases['etl']}/documents/{did}")
            except httpx.HTTPError:
                pass
        if audit_id:
            try:
                await client.delete(f"{bases['audit']}/audits/{audit_id}")
            except httpx.HTTPError:
                pass
        if app_id:
            try:
                await client.delete(f"{bases['generateur']}/apps/{app_id}")
                await client.delete(f"{bases['donnees']}/apps/{app_id}")
            except httpx.HTTPError:
                pass

    orchestrateur.marquer_decrochee(livraison_id, str(chemin))
    return {
        "decrochee": True,
        "nom_entreprise": liv.get("nom_entreprise"),
        "dossier": str(base),
        "fichier": "dossier.json",
        "documents": len(dossier["documents"]),
        "donnees": sum(len(v) for v in dossier["donnees"].values()),
        "note": "Dossier monté sur l'hôte dans ~/Desktop/Workplace/apps_exportees/",
    }


# ── REPRENDRE ────────────────────────────────────────────────────────────────

async def _reinjecter(registre, data: dict) -> dict:
    """Réinjecte le contenu d'un dossier dans les briques (export → import)."""
    bases = _bases(registre)
    rapport = {"documents": 0, "audit": False, "app": False, "donnees": 0}

    async with httpx.AsyncClient(timeout=60) as client:
        for doc in data.get("documents") or []:
            r = await client.post(f"{bases['etl']}/documents/import", json=doc)
            if r.status_code < 400:
                rapport["documents"] += 1

        if data.get("audit"):
            r = await client.post(f"{bases['audit']}/audits/import", json=data["audit"])
            rapport["audit"] = r.status_code < 400

        app = data.get("app")
        if app:
            # Le dossier porte `partage_forge` (consentement du pont app→CRM, S24) :
            # `/apps/import` ré-arme le pont si le consentement était actif. Au
            # décrochage, la suppression de l'app a naturellement arrêté le pont
            # (aucune purge du CRM — décision : purge sur demande explicite seulement).
            r = await client.post(f"{bases['generateur']}/apps/import", json=app)
            rapport["app"] = r.status_code < 400
            app_id = app.get("id")
            donnees = data.get("donnees") or {}
            if app_id and donnees:
                r = await client.post(
                    f"{bases['donnees']}/apps/{app_id}/import", json={"entites": donnees},
                    headers=contexte_tenant.entetes_donnees(),
                )
                if r.status_code < 400:
                    rapport["donnees"] = r.json().get("nombre", 0)
    return rapport


async def reprendre(registre, livraison_id: str) -> dict:
    """Reprend une entreprise décrochée (par son id de livraison)."""
    liv = orchestrateur.lire_livraison(livraison_id)
    if not liv:
        raise ValueError("Livraison introuvable")
    if liv.get("statut") != "decrochee":
        raise ValueError("Cette entreprise n'est pas de côté (statut ≠ décrochée)")
    chemin = liv.get("dossier")
    if not chemin or not Path(chemin).exists():
        raise EchecCycle(f"Dossier introuvable sur disque : {chemin}")

    data = json.loads(Path(chemin).read_text(encoding="utf-8"))
    rapport = await _reinjecter(registre, data)
    orchestrateur.marquer_reprise(livraison_id)
    return {"reprise": True, "nom_entreprise": liv.get("nom_entreprise"), **rapport}
