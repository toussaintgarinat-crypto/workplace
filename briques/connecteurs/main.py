"""Brique « connecteurs » (S214) — la donnée structurée des tiers, planifiée et reprenable.

Port 6200. Ce que la brique apporte au parc : jusqu'ici chaque brique bricolait son propre
fetch (`veille-info` fait du RSS, `gateway-sync` appelle OpenRouter) sans état partagé,
sans reprise, sans mutualisation — le connecteur suivant aurait été réécrit à la main.
Ici, une source = un connecteur Airbyte + une configuration chiffrée, et la synchro est
incrémentale : on ne retransfère que le delta depuis le dernier curseur.

**Ce que la brique n'est pas** : un entrepôt. Les données atterrissent dans le cache
DuckDB local de PyAirbyte et y restent (décision de l'ADR, non-sprint `entrepot` assumé).
La brique `donnees` (5500) est un CRUD multi-tenant, pas une destination analytique.

PyAirbyte n'est jamais importé ici : il vit derrière une cloison de processus (cf. pont.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import coffre
import pont
import stockage

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("connecteurs")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    stockage.initialiser()
    # Une sync « en_cours » au démarrage est le vestige d'un processus tué : le conteneur
    # a redémarré en plein transfert. On le dit au lieu de laisser la ligne mentir.
    reprises = stockage.rouvrir_syncs_orphelines()
    if reprises:
        logger.warning("Démarrage : %d sync(s) interrompue(s) par un arrêt du conteneur — "
                       "la prochaine reprendra au dernier curseur.", reprises)
    logger.info("Brique connecteurs démarrée (pont PyAirbyte %s)",
                "disponible" if pont.disponible() else "INDISPONIBLE")
    yield


app = FastAPI(title="Workplace — Brique connecteurs",
              description="Connecteurs Airbyte pilotés en librairie : sync incrémentale, "
                          "état persisté, reprise après interruption.",
              version=VERSION, lifespan=lifespan)

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Résout le tenant — motif `veille-info` (S185) repris tel quel, deux dialectes :

    (a) **Cœur / cercle privé** : la clé présentée == `CONNECTEURS_KEY` (SEUL le Cœur la
        détient) ⇒ il emprunte l'identité de la personne connectée via `X-User-Id`. Chaque
        membre du foyer a SES sources et SES curseurs, même clé partagée.
    (b) **Tenant externe (bundle-client)** : toute AUTRE clé ⇒ le tenant est l'empreinte
        sha256 tronquée de la clé.

    Fail-closed si `API_KEYS` est défini ; sinon (dev) « public »."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    cle_coeur = os.environ.get("CONNECTEURS_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /sync/executer : jeton partagé `CONNECTEURS_KEY`, PAS `tenant_actuel` —
    cette route traite TOUTES les sources du parc en un appel, elle n'est scopée à aucun
    tenant. Fail-closed si `CONNECTEURS_KEY` est défini."""
    attendu = os.environ.get("CONNECTEURS_KEY")
    if not attendu:
        return
    if (authorization or "").removeprefix("Bearer ").strip() != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    """Reste réactif PENDANT une sync : le transfert tourne dans un autre processus
    (cf. pont.py). C'est le défaut que S212 a corrigé sur `ingestion`, évité ici par construction."""
    return {"statut": "ok", "version": VERSION, "pont_pyairbyte": pont.disponible()}


# ── Sources ──────────────────────────────────────────────────────────────────

class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    connecteur: str = Field(min_length=1, description="Nom PyPI du connecteur, ex. source-github")
    config: dict = Field(default_factory=dict)
    flux: list[str] = Field(default_factory=list)


class ModifierSource(BaseModel):
    config: dict | None = None
    flux: list[str] | None = None


class BasculerActive(BaseModel):
    active: bool


def _source_ou_404(tenant: str, source_id: int) -> dict:
    src = stockage.source_get(tenant, source_id)
    if src is None:
        raise HTTPException(404, "Source introuvable.")
    return src


@app.get("/sources", tags=["sources"])
def lister_sources_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_sources(tenant)


@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(corps: CreerSource, tenant: str = Depends(tenant_actuel)):
    """Créer une source n'est PAS une capacité de l'assistant, à dessein : la config porte
    des identifiants tiers, et une capacité les ferait transiter par une conversation LLM
    (donc par le journal, le cache sémantique et le fournisseur du modèle). On les saisit
    par l'API ou par l'atelier ; l'assistant, lui, déclenche et consulte."""
    try:
        return stockage.creer_source(tenant, corps.nom, corps.connecteur, corps.config, corps.flux)
    except coffre.SecretIndisponible as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # sqlite3.IntegrityError : (tenant, nom) déjà pris
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"Une source nommée « {corps.nom} » existe déjà.")
        raise


@app.get("/sources/{source_id}", tags=["sources"])
def lire_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    src = _source_ou_404(tenant, source_id)
    return {**src, "etats": stockage.etats_vue(source_id),
            "derniere_sync": next(iter(stockage.lister_syncs(tenant, source_id, 1)), None)}


@app.patch("/sources/{source_id}", tags=["sources"])
def modifier_source_route(source_id: int, corps: ModifierSource,
                          tenant: str = Depends(tenant_actuel)):
    _source_ou_404(tenant, source_id)
    stockage.modifier_source(tenant, source_id, config=corps.config, flux=corps.flux)
    return stockage.source_get(tenant, source_id)


@app.patch("/sources/{source_id}/actif", tags=["sources"])
def basculer_source_route(source_id: int, corps: BasculerActive,
                          tenant: str = Depends(tenant_actuel)):
    """Éteindre une source la sort de la sync quotidienne SANS toucher à son curseur :
    rallumée, elle reprend où elle en était plutôt que de tout retransférer."""
    _source_ou_404(tenant, source_id)
    stockage.modifier_source(tenant, source_id, active=corps.active)
    return {"ok": True, "active": corps.active}


@app.delete("/sources/{source_id}", tags=["sources"])
def supprimer_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    if not stockage.supprimer_source(tenant, source_id):
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}


@app.delete("/sources/{source_id}/etat", tags=["sources"])
def oublier_etat_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    """Oublie le curseur : la prochaine sync repart du début.

    Honnêteté sur la portée : cela vide le curseur MIROIR de la brique. Le cache PyAirbyte
    garde le sien — c'est le drapeau `complet` de la sync qui l'ignore réellement
    (`force_full_refresh`). On rend donc les deux informations plutôt que de laisser croire
    à une remise à zéro totale."""
    _source_ou_404(tenant, source_id)
    n = stockage.oublier_etats(source_id)
    return {"ok": True, "curseurs_oublies": n,
            "note": "Pour retransférer réellement depuis le début, lancer une sync avec "
                    "complet=true (force_full_refresh côté connecteur)."}


# ── Syncs ────────────────────────────────────────────────────────────────────

class DemandeSync(BaseModel):
    complet: bool = False


# Les tâches de fond sont RÉFÉRENCÉES : asyncio ne garde qu'une référence faible sur une
# tâche, et une sync de plusieurs minutes peut être ramassée par le GC en plein transfert
# (piège documenté d'asyncio.create_task).
_EN_VOL: set[asyncio.Task] = set()


async def _syncer(tenant: str, source_id: int, sync_id: int, complet: bool) -> None:
    """Exécute une sync de bout en bout et tient la comptabilité. Ne lève jamais :
    un échec est une DONNÉE (`syncs.erreur`), lisible par l'assistant."""
    details = stockage.config_de(tenant, source_id)
    if details is None:
        stockage.cloturer_sync(sync_id, "echec", erreur="source supprimée pendant la sync")
        return
    connecteur, config, flux = details
    job = {"action": "sync", "connecteur": connecteur, "config": config, "flux": flux,
           "complet": complet, "schema": pont.schema_de(tenant, source_id),
           "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")}
    try:
        reponse = await pont.executer(job)
    except pont.PontIndisponible as e:
        stockage.cloturer_sync(sync_id, "echec", erreur=str(e))
        return

    if not reponse.get("ok"):
        stockage.cloturer_sync(sync_id, "echec", erreur=reponse.get("erreur", "échec inconnu"))
        return

    # Le curseur est recopié dans SQLite : c'est ce qui rend l'incrémental vérifiable
    # (une route peut le rendre, deux syncs peuvent être comparées) sans avoir à ouvrir
    # le cache DuckDB de la librairie.
    for nom_flux, curseur in (reponse.get("etats") or {}).items():
        stockage.enregistrer_etat(source_id, nom_flux, curseur)
    stockage.cloturer_sync(sync_id, "ok",
                           nb_enregistrements=int(reponse.get("nb_enregistrements") or 0))


def _lancer_sync(tenant: str, source_id: int, complet: bool = False) -> dict:
    """Ouvre une sync et la lance en fond. Rend immédiatement — un transfert peut durer
    des minutes, et ni l'assistant ni l'horloge (timeout 120 s côté Cœur) ne peuvent
    attendre au bout d'une requête HTTP.

    Idempotent : si une sync est déjà en cours sur cette source, on rend CELLE-LÀ plutôt
    que d'en ouvrir une seconde qui se battrait avec elle pour le même curseur.

    ⚠ Les deux routes qui appellent ceci sont `async def`, et ce n'est pas un détail de
    style : une route `def` est exécutée par FastAPI dans un thread du pool, où
    `asyncio.create_task` lève « no running event loop ». Le défaut a été écrit puis
    attrapé par `test_la_sync_rend_la_main_avant_la_fin_du_transfert` — d'où ce rappel."""
    en_cours = [s for s in stockage.lister_syncs(tenant, source_id, 5) if s["statut"] == "en_cours"]
    if en_cours:
        return {**en_cours[0], "deja_en_cours": True}
    sync_id = stockage.ouvrir_sync(tenant, source_id)
    tache = asyncio.create_task(_syncer(tenant, source_id, sync_id, complet))
    _EN_VOL.add(tache)
    tache.add_done_callback(_EN_VOL.discard)
    return {**stockage.sync_get(tenant, sync_id), "deja_en_cours": False}


@app.post("/sources/{source_id}/sync", tags=["syncs"], status_code=202)
async def declencher_sync_route(source_id: int,
                                corps: DemandeSync = Body(default_factory=DemandeSync),
                                tenant: str = Depends(tenant_actuel)):
    _source_ou_404(tenant, source_id)
    return _lancer_sync(tenant, source_id, corps.complet)


@app.get("/syncs", tags=["syncs"])
def lister_syncs_route(source_id: int | None = None, limite: int = 50,
                       tenant: str = Depends(tenant_actuel)):
    return stockage.lister_syncs(tenant, source_id, max(1, min(limite, 500)))


@app.get("/syncs/{sync_id}", tags=["syncs"])
def lire_sync_route(sync_id: int, tenant: str = Depends(tenant_actuel)):
    s = stockage.sync_get(tenant, sync_id)
    if s is None:
        raise HTTPException(404, "Synchro introuvable.")
    return s


# ── Diagnostic d'une source (hors capacités : trop bavard pour un outil LLM) ──

@app.post("/sources/{source_id}/verifier", tags=["diagnostic"])
async def verifier_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    """`check` du connecteur : les identifiants passent-ils ? À appeler après saisie."""
    details = stockage.config_de(tenant, source_id)
    if details is None:
        raise HTTPException(404, "Source introuvable.")
    connecteur, config, _ = details
    return await pont.executer(
        {"action": "verifier", "connecteur": connecteur, "config": config,
         "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")},
        timeout=pont.TIMEOUT_COURT)


@app.get("/sources/{source_id}/flux", tags=["diagnostic"])
async def lister_flux_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    """`discover` du connecteur : quels flux ce tiers propose-t-il ?"""
    details = stockage.config_de(tenant, source_id)
    if details is None:
        raise HTTPException(404, "Source introuvable.")
    connecteur, config, _ = details
    return await pont.executer(
        {"action": "flux", "connecteur": connecteur, "config": config,
         "racine": os.getenv("CONNECTEURS_TRAVAIL", "/travail")},
        timeout=pont.TIMEOUT_COURT)


# ── Tâche horloge ────────────────────────────────────────────────────────────

@app.post("/sync/executer", tags=["horloge"])
async def executer_sync_quotidienne_route(_: None = Depends(verifier_cle_horloge)):
    """Synchronise toutes les sources ACTIVES du parc, tous tenants confondus.

    Rend immédiatement la liste des syncs ouvertes : le Cœur coupe à 120 s
    (`core/horloge.py::_executer`), et un plein de dépôt GitHub dépasse ce délai. Ce qui
    est journalisé côté horloge est donc « j'ai bien lancé N syncs », pas « N syncs ont
    réussi » — la réussite se lit dans `/syncs`. Dire l'un pour l'autre serait un faux
    vert quotidien."""
    lancees = []
    for tenant, source_id in stockage.sources_actives():
        lancees.append({"tenant_masque": tenant[:8], "source_id": source_id,
                        **_lancer_sync(tenant, source_id)})
    return {"ok": True, "nb_sources_actives": len(lancees), "syncs": lancees}
