"""Brique « forge » — adaptateur entre Workplace et le core Forge.

Le core Forge (FastAPI, ~28 000 lignes : agents IA, RAG, CRM, ventures…) est
riche mais monte ses routes fonctionnelles derrière `get_current_user` (Keycloak).
Cette brique l'enveloppe derrière un **contrat Workplace en français** que le Cœur
et son assistant peuvent consommer sans rien connaître de l'API interne.

Auth (S17, voie 2 tranchée en S16). L'adaptateur obtient un **token de service**
(`client_credentials`, client `forge-service`) auprès du **Keycloak d'Oria** et le
présente en `Bearer` sur chaque route protégée qu'il proxifie. Le core ne vérifie
ni l'issuer ni l'audience (multi-tenant) ⇒ tout JWT signé par le realm `oria` est
accepté. Le token est mis en cache et rafraîchi avant expiration.

Contrat exposé :
    GET  /sante        → santé agrégée (core + DB)                    [public]
    GET  /capacites    → ce que Forge sait faire                      [public]
    GET  /agents       → liste des agents Forge (preuve schéma+auth)  [auth service]

Le reste du cycle fonctionnel (lancer un agent, ingérer/chercher en RAG) s'ajoute
ici aux Chantiers 2-3 de S17, en réutilisant le même helper d'appel authentifié.

Tolérant aux pannes : `/sante` dégrade en 503 si le core est down ; les routes
authentifiées renvoient un message clair (502/503) si Keycloak ou le core manquent,
plutôt qu'une stacktrace — le Cœur doit pouvoir afficher un état honnête.
"""

import asyncio
import contextvars
import os
import time

import httpx
from fastapi import Body, FastAPI, HTTPException

# URL du core Forge. En conteneur, on l'atteint par le DNS de compose (`forge`).
FORGE_CORE_URL = os.environ.get("FORGE_CORE_URL", "http://forge:8600").rstrip("/")

# ── Auth de service (Keycloak d'Oria) ─────────────────────────────────────────
KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://host.docker.internal:8081").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "oria")
SERVICE_CLIENT_ID = os.environ.get("FORGE_SERVICE_CLIENT_ID", "forge-service")
SERVICE_SECRET = os.environ.get("FORGE_SERVICE_SECRET", "")
_TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

CAPACITES = {
    "agents_ia": {
        "famille": "agents_ia",
        "titre": "Agents IA",
        "description": "Lancer des agents IA (raisonnement + outils) sur des tâches.",
        "disponible_sans_auth": False,
    },
    "rag": {
        "famille": "rag",
        "titre": "RAG (questions sur documents)",
        "description": "Ingérer des documents et répondre par recherche augmentée.",
        "disponible_sans_auth": False,
    },
    "vectorisation": {
        "famille": "vectorisation",
        "titre": "Vectorisation",
        "description": "Indexer des contenus en base vectorielle pour la recherche sémantique.",
        "disponible_sans_auth": False,
    },
    "facturation": {
        "famille": "facturation",
        "titre": "Facturation (devis & factures)",
        "description": "Lister, créer des devis/factures, transformer un devis en facture "
                       "et suivre l'encaissement (chiffre d'affaires, impayés).",
        "disponible_sans_auth": False,
    },
    "crm": {
        "famille": "crm",
        "titre": "CRM (prospects & pipeline commercial)",
        "description": "Suivre les prospects/clients : lister, ajouter, faire avancer dans "
                       "le pipeline (statut, valeur estimée) pour piloter la vente.",
        "disponible_sans_auth": False,
    },
    "paiement": {
        "famille": "paiement",
        "titre": "Paiement en ligne (Stripe)",
        "description": "Encaisser en ligne via Stripe : créer un lien de paiement pour un "
                       "plan, consulter l'abonnement et l'historique des paiements. La "
                       "configuration de la clé se fait hors assistant (coffre chiffré).",
        "disponible_sans_auth": False,
    },
    "relances": {
        "famille": "relances",
        "titre": "Emails & relances d'impayés",
        "description": "Envoyer une facture par email et relancer automatiquement les "
                       "factures impayées (J+7/J+15/J+30, anti-doublon). Aperçu avant envoi, "
                       "exécution et journal des relances.",
        "disponible_sans_auth": False,
    },
}

app = FastAPI(title="Forge Workplace", version="0.2.0")


# ── Propagation d'identité utilisateur (dette S20) ───────────────────────────────
# L'adaptateur s'authentifie au core avec un **token de service** (choix S16/S17). Mais
# pour les opérations scopées par utilisateur/organisation, l'identité réelle doit
# pouvoir traverser. Si l'appelant (le Cœur) fournit le JWT de l'utilisateur dans
# l'en-tête `X-Forge-User-Token`, on le **propage** au core (qui provisionne/scope par cet
# utilisateur) ; sinon on retombe sur le token de service (rétrocompatible, flux S17/S24
# inchangés). Le token voyage par requête via un ContextVar → aucune signature de route à
# modifier, et `_resoudre_pole_crm` (qui rappelle `_appel_protege`) en bénéficie aussi.
_JETON_UTILISATEUR: "contextvars.ContextVar[str | None]" = contextvars.ContextVar(
    "forge_user_token", default=None
)


@app.middleware("http")
async def _capter_jeton_utilisateur(request, call_next):
    brut = request.headers.get("X-Forge-User-Token")
    token = brut.split(" ", 1)[1] if brut and brut.lower().startswith("bearer ") else brut
    jeton = _JETON_UTILISATEUR.set(token or None)
    try:
        return await call_next(request)
    finally:
        _JETON_UTILISATEUR.reset(jeton)


async def _client(timeout: float = 15) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


# ── Jeton de service Keycloak (cache + refresh) ────────────────────────────────

class _ServiceAuth:
    """Obtient et met en cache un token `client_credentials`, rafraîchi avant péremption.

    Thread-safe (lock asyncio) : un seul refresh concurrent. On garde une marge de
    30 s avant l'expiration annoncée par Keycloak (`expires_in`, ~300 s).
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._exp_monotonic: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def configure(self) -> bool:
        return bool(SERVICE_SECRET)

    async def token(self, client: httpx.AsyncClient) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._exp_monotonic - 30:
                return self._token
            r = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": SERVICE_CLIENT_ID,
                    "client_secret": SERVICE_SECRET,
                },
            )
            r.raise_for_status()
            d = r.json()
            self._token = d["access_token"]
            self._exp_monotonic = time.monotonic() + float(d.get("expires_in", 300))
            return self._token

    def invalider(self) -> None:
        """Force un renouvellement au prochain appel : le jeton mémoïsé peut avoir été
        révoqué côté Keycloak avant sa péremption annoncée (secret changé, client
        désactivé) — `token()` ne vérifie que l'horloge, jamais l'acceptation réelle par
        le core (même trou que celui corrigé dans briques/memoire, constaté 2026-07-23)."""
        self._token = None
        self._exp_monotonic = 0.0


_auth = _ServiceAuth()


async def _appel_protege(
    client: httpx.AsyncClient, methode: str, chemin: str, **kw
) -> httpx.Response:
    """Appelle une route protégée du core en Bearer.

    Identité (dette S20) : si l'appelant a fourni le JWT de l'utilisateur
    (`X-Forge-User-Token`, capté dans le ContextVar), on le **propage** — le core scope
    alors par l'utilisateur réel. Sinon, repli sur le **token de service** (comportement
    historique S17, flux service/S24 inchangés).

    Mappe les pannes en HTTPException claires (jamais de stacktrace au Cœur) :
    - secret absent (et pas de token utilisateur) → 503 ;
    - Keycloak injoignable / refus → 502 ;
    - core injoignable → 503.
    """
    jeton_utilisateur = _JETON_UTILISATEUR.get()
    entetes_supp = kw.pop("headers", {})
    if jeton_utilisateur:
        token = jeton_utilisateur
    else:
        if not _auth.configure:
            raise HTTPException(503, "Auth de service non configurée (FORGE_SERVICE_SECRET absent).")
        try:
            token = await _auth.token(client)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Jeton de service Keycloak indisponible : {e}")
    headers = {**entetes_supp, "Authorization": f"Bearer {token}"}
    try:
        r = await client.request(methode, f"{FORGE_CORE_URL}{chemin}", headers=headers, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Core Forge injoignable : {e}")
    # Filet de retry (même motif que briques/memoire, bug constaté 2026-07-23) : un 401
    # sur le jeton de SERVICE mémoïsé peut signifier qu'il a été révoqué avant sa
    # péremption annoncée — on invalide le cache et on réessaie UNE fois avec un jeton
    # frais. Un 401 sur un jeton UTILISATEUR n'est PAS retenté : Forge n'a aucun moyen
    # d'obtenir un meilleur jeton utilisateur, seul l'appelant original peut en fournir un.
    if r.status_code == 401 and not jeton_utilisateur:
        _auth.invalider()
        try:
            token = await _auth.token(client)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"Jeton de service Keycloak indisponible : {e}")
        headers = {**entetes_supp, "Authorization": f"Bearer {token}"}
        try:
            r = await client.request(methode, f"{FORGE_CORE_URL}{chemin}", headers=headers, **kw)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"Core Forge injoignable : {e}")
    return r


# ── Contrat ────────────────────────────────────────────────────────────────────

@app.get("/sante", summary="Santé agrégée de Forge (core + base de données)")
async def sante():
    """OK seulement si le core Forge répond ET que sa base est saine."""
    try:
        async with await _client() as client:
            pub = await client.get(f"{FORGE_CORE_URL}/api/health")
            db = await client.get(f"{FORGE_CORE_URL}/health")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Core Forge injoignable : {e}")

    if pub.status_code >= 400:
        raise HTTPException(503, f"Core Forge en erreur (HTTP {pub.status_code})")

    db_corps = db.json() if db.status_code < 400 else {}
    degrade = bool(db_corps.get("degraded")) or db.status_code >= 400

    return {
        "statut": "degrade" if degrade else "ok",
        "service": "forge",
        "version": "0.2.0",
        "auth_service": "configurée" if _auth.configure else "absente",
        "core": {
            "version": db_corps.get("version"),
            "uptime_s": db_corps.get("uptime_seconds"),
            "dependances": db_corps.get("dependencies", []),
        },
    }


@app.get("/capacites", summary="Ce que Forge sait faire")
async def capacites():
    """Familles d'offres déclarées par Forge, avec leur disponibilité."""
    core_ok = False
    try:
        async with await _client() as client:
            r = await client.get(f"{FORGE_CORE_URL}/api/health")
            core_ok = r.status_code < 400
    except httpx.HTTPError:
        core_ok = False

    capas = list(CAPACITES.values())
    return {
        "service": "forge",
        "core_en_ligne": core_ok,
        "auth_service": "configurée" if _auth.configure else "absente",
        "total": len(capas),
        "capacites": capas,
        "note": "Le fonctionnel (agents, RAG) requiert l'auth de service — activée en S17.",
    }


@app.get("/agents", summary="Liste des agents Forge (preuve schéma + auth de service)")
async def agents():
    """Proxy authentifié de `GET /api/agents`. Preuve du Chantier 0 :

    un 200 ici signifie que le schéma DB est migré (provisioning user réussi) ET
    que le token de service est accepté par le core.
    """
    async with await _client() as client:
        r = await _appel_protege(client, "GET", "/api/agents")
    return _json_ou_erreur(r)


# ── Fonctionnel RAG + agents (S17 C2) ──────────────────────────────────────────

def _json_ou_erreur(r: httpx.Response):
    """Renvoie le JSON du core, ou mappe l'erreur en message clair (jamais brut)."""
    if r.status_code == 401:
        raise HTTPException(502, "Core Forge a refusé le token de service (401).")
    if r.status_code == 404:
        raise HTTPException(502, "Route Forge introuvable (404) — schéma/route absente ?")
    if r.status_code >= 400:
        raise HTTPException(502, f"Core Forge en erreur (HTTP {r.status_code}) : {r.text[:200]}")
    return r.json()


@app.post("/rag/ingerer", summary="Ingérer un document dans le RAG de Forge (vectorisation)")
async def rag_ingerer(corps: dict = Body(...)):
    """Proxy authentifié → `POST /api/documents/upload`. ACTION (écrit dans Forge + Qdrant).

    Entrée : ``{nom, contenu, type?}``. Le core analyse (LLM), persiste le document
    et ingère ses chunks dans Qdrant (embeddings all-minilm via la Gateway).
    """
    nom = (corps.get("nom") or "").strip()
    contenu = (corps.get("contenu") or "").strip()
    if not nom or not contenu:
        raise HTTPException(422, "Champs requis : 'nom' et 'contenu'.")
    charge = {"nom": nom, "contenu": contenu, "type": corps.get("type") or "txt"}
    async with await _client(timeout=60) as client:
        r = await _appel_protege(client, "POST", "/api/documents/upload", json=charge)
    doc = _json_ou_erreur(r)
    return {
        "ok": True,
        "id": doc.get("id"),
        "nom": doc.get("nom"),
        "taille": doc.get("taille"),
        "message": f"Document « {doc.get('nom')} » ingéré dans le RAG de Forge.",
    }


@app.get("/rag/chercher", summary="Recherche sémantique dans les documents ingérés (RAG)")
async def rag_chercher(q: str = "", seuil: float | None = None, limite: int | None = None):
    """Proxy authentifié → `GET /api/rag/search`. Lecture seule (pas de LLM, pas d'écriture)."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(422, "Paramètre requis : 'q' (la question).")
    params: dict = {"q": q}
    if seuil is not None:
        params["seuil"] = seuil
    if limite is not None:
        params["limite"] = limite
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "GET", "/api/rag/search", params=params)
    data = _json_ou_erreur(r)
    return {
        "question": data.get("query", q),
        "trouve": data.get("found", False),
        "passages": data.get("passages", ""),
    }


@app.post("/agent/lancer", summary="Lancer un agent IA Forge sur une tâche")
async def agent_lancer(corps: dict = Body(...)):
    """Proxy authentifié → `POST /api/agents/run`. ACTION (l'agent raisonne via la Gateway 4001).

    Entrée : ``{objectif}`` (+ ``contexte`` optionnel, concaténé à l'objectif).
    """
    objectif = (corps.get("objectif") or corps.get("task") or "").strip()
    if not objectif:
        raise HTTPException(422, "Champ requis : 'objectif'.")
    contexte = (corps.get("contexte") or "").strip()
    tache = f"{objectif}\n\nContexte :\n{contexte}" if contexte else objectif
    async with await _client(timeout=180) as client:
        r = await _appel_protege(client, "POST", "/api/agents/run", json={"task": tache})
    data = _json_ou_erreur(r)
    return {"ok": True, "reponse": data.get("result", "")}


# ── Facturation : devis, factures, encaissement (S20 C1) ────────────────────────
#
# Proxy authentifié du router `facturation` du core (numérotation auto, calcul
# HT/TVA/TTC, transformation devis→facture). Le core scope par `user_id` ; via le
# token de service, tout vit sous l'identité unique de Workplace (cf. S20 — modèle
# mono-propriétaire : pas de fuite inter-tenant car une seule identité traverse
# l'adaptateur). Contrat exposé en français, montants prêts pour l'affichage.

# Statuts de facture autorisés à l'écriture depuis Workplace (parité core Bun).
_STATUTS_FACTURE = {"brouillon", "envoyée", "payée", "annulée"}


def _resume_facture(d: dict) -> dict:
    """Réduit un document core (camelCase, lignes JSON brut) à un résumé français."""
    return {
        "id": d.get("id"),
        "numero": d.get("numero"),
        "type": d.get("type"),
        "client": d.get("clientNom"),
        "statut": d.get("statut"),
        "montant_ttc": d.get("totalTtc"),
        "montant_ht": d.get("totalHt"),
        "date_emission": d.get("dateEmission") or None,
        "date_echeance": d.get("dateEcheance") or None,
        "date_paiement": d.get("datePaiement") or None,
    }


@app.get("/facturation", summary="Lister les devis/factures + chiffre d'affaires (lecture)")
async def facturation_lister(type: str | None = None, statut: str | None = None):
    """Proxy authentifié → `GET /api/facturation`. Lecture seule.

    `type` filtre (`facture`/`devis`) ; `statut` filtre côté adaptateur (ex.
    « impayés » = factures `envoyée`). Renvoie les résumés + les stats de CA
    (encaissé, en attente) calculées par le core.
    """
    params = {"type": type} if type in ("facture", "devis") else {}
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "GET", "/api/facturation", params=params)
    data = _json_ou_erreur(r)
    items = [_resume_facture(d) for d in data.get("items", [])]
    if statut:
        items = [i for i in items if i["statut"] == statut]
    stats = data.get("stats", {})
    return {
        "total": len(items),
        "documents": items,
        "ca": {
            "encaisse": stats.get("caTotal", 0.0),
            "en_attente": stats.get("caEnAttente", 0.0),
            "nb_factures": stats.get("nbFactures", 0),
            "nb_devis": stats.get("nbDevis", 0),
        },
    }


@app.post("/facturation", summary="Créer un devis ou une facture (action)")
async def facturation_creer(corps: dict = Body(...)):
    """Proxy authentifié → `POST /api/facturation`. ACTION (écrit dans Forge).

    Entrée française : ``{client, type?, lignes:[{description, quantite?,
    prix_unitaire, tva?}], email?, tva_taux?, notes?, echeance?}``. Le core
    numérote (FACT/DEVIS-AAAA-NNNN) et calcule HT/TVA/TTC.
    """
    client_nom = (corps.get("client") or "").strip()
    lignes = corps.get("lignes") or []
    if not client_nom:
        raise HTTPException(422, "Champ requis : 'client'.")
    if not lignes:
        raise HTTPException(422, "Champ requis : 'lignes' (au moins une ligne).")
    type_ = corps.get("type") or "facture"
    if type_ not in ("facture", "devis"):
        raise HTTPException(422, "'type' doit être 'facture' ou 'devis'.")
    lignes_core = []
    for l in lignes:
        desc = (l.get("description") or "").strip()
        if not desc:
            raise HTTPException(422, "Chaque ligne doit avoir une 'description'.")
        lignes_core.append({
            "description": desc,
            "quantite": l.get("quantite", 1),
            "prixUnitaire": l.get("prix_unitaire", l.get("prixUnitaire", 0)),
            "tva": l.get("tva", corps.get("tva_taux", 20)),
        })
    charge = {
        "type": type_,
        "clientNom": client_nom,
        "clientEmail": corps.get("email") or None,
        "lignes": lignes_core,
        "tvaTaux": corps.get("tva_taux", 20),
        "notes": corps.get("notes") or None,
        "dateEcheance": corps.get("echeance") or None,
    }
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "POST", "/api/facturation", json=charge)
    doc = _json_ou_erreur(r)
    resume = _resume_facture(doc)
    libelle = "Devis" if type_ == "devis" else "Facture"
    return {
        "ok": True,
        **resume,
        "message": f"{libelle} {doc.get('numero')} créé(e) pour {client_nom} "
                   f"({resume['montant_ttc']} € TTC).",
    }


@app.post("/facturation/{did}/statut", summary="Changer le statut d'une facture (action)")
async def facturation_statut(did: str, corps: dict = Body(...)):
    """Proxy authentifié → `PATCH /api/facturation/{id}`. ACTION (écrit dans Forge).

    Sert l'encaissement : passer une facture à `payée` (avec date de paiement)
    la fait basculer dans le CA encaissé. Statuts : brouillon, envoyée, payée, annulée.
    """
    statut = (corps.get("statut") or "").strip()
    if statut not in _STATUTS_FACTURE:
        raise HTTPException(422, f"'statut' doit être l'un de : {', '.join(sorted(_STATUTS_FACTURE))}.")
    charge: dict = {"statut": statut}
    if statut == "payée":
        charge["datePaiement"] = corps.get("date_paiement") or time.strftime("%Y-%m-%d")
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "PATCH", f"/api/facturation/{did}", json=charge)
    doc = _json_ou_erreur(r)
    if not doc:
        raise HTTPException(404, "Facture introuvable.")
    return {"ok": True, **_resume_facture(doc),
            "message": f"Document {doc.get('numero')} passé au statut « {statut} »."}


@app.post("/facturation/{did}/transformer", summary="Transformer un devis en facture (action)")
async def facturation_transformer(did: str):
    """Proxy authentifié → `POST /api/facturation/{id}/transformer`. ACTION.

    Crée une facture (brouillon) à partir d'un devis et marque le devis comme transformé.
    """
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "POST", f"/api/facturation/{did}/transformer")
    doc = _json_ou_erreur(r)
    return {"ok": True, **_resume_facture(doc),
            "message": f"Devis transformé en facture {doc.get('numero')}."}


# ── CRM : prospects & pipeline commercial (S20 C2) ──────────────────────────────
#
# Le router CRM du core scope les leads par `pole_id` **et** `user_id`. Workplace
# étant mono-entreprise, on masque le cérémonial venture→pôle : l'adaptateur résout
# (et amorce paresseusement, une seule fois) un pôle commercial par défaut, puis
# expose un contrat simple « prospects ». Même modèle d'identité que la facturation
# (token de service unique ⇒ une seule identité Forge — cf. S20, dette d'identité).

# Pôle commercial résolu une fois puis mémorisé (durée de vie du process adaptateur).
_pole_crm_cache: str | None = None


async def _resoudre_pole_crm(client: httpx.AsyncClient) -> str:
    """Renvoie l'id d'un pôle commercial, en l'amorçant si la base est vierge.

    On passe par la **venture** (et non `GET /api/poles`, qui filtre par `org_id`
    alors que les pôles amorcés ont `org_id` nul ⇒ liste vide en boucle) :
    lister les ventures (scopées par `owner_id`, fiables) → en créer une « Workplace »
    si aucune (le core crée 6 pôles par défaut, dont *Sales*) → lister ses pôles
    (`/ventures/{id}/poles`, scopé par venture) → préférer *Sales*, sinon le 1er.
    Résultat mémorisé pour la durée de vie du process.
    """
    global _pole_crm_cache
    if _pole_crm_cache:
        return _pole_crm_cache
    ventures = _json_ou_erreur(await _appel_protege(client, "GET", "/api/ventures"))
    if not ventures:
        _json_ou_erreur(await _appel_protege(
            client, "POST", "/api/ventures",
            json={"nom": "Workplace", "type": "own", "description": "Espace commercial Workplace"}))
        ventures = _json_ou_erreur(await _appel_protege(client, "GET", "/api/ventures"))
    vid = ventures[0].get("id") if ventures else None
    if not vid:
        raise HTTPException(502, "Impossible de résoudre une venture commerciale dans Forge.")
    poles = _json_ou_erreur(await _appel_protege(client, "GET", f"/api/ventures/{vid}/poles"))
    pole = next((p for p in poles if p.get("type") == "sales"), None) or (poles[0] if poles else None)
    if not pole or not pole.get("id"):
        raise HTTPException(502, "Impossible de résoudre un pôle commercial dans Forge.")
    _pole_crm_cache = pole["id"]
    return _pole_crm_cache


_CHAMPS_LEAD = ("nom", "email", "telephone", "entreprise", "statut", "valeur", "notes")


def _resume_lead(d: dict) -> dict:
    """Réduit un lead core (camelCase) à un résumé français."""
    return {
        "id": d.get("id"),
        "nom": d.get("nom"),
        "entreprise": d.get("entreprise") or None,
        "email": d.get("email") or None,
        "telephone": d.get("telephone") or None,
        "statut": d.get("statut"),
        "valeur": d.get("valeur"),
        "notes": d.get("notes") or None,
    }


@app.get("/crm", summary="Lister les prospects + pipeline commercial (lecture)")
async def crm_lister(statut: str | None = None):
    """Proxy authentifié → `GET /api/poles/{pole}/crm`. Lecture seule.

    Renvoie les prospects (filtrés par `statut` si fourni) et un récapitulatif de
    pipeline : valeur totale estimée + ventilation par statut (nombre et valeur).
    """
    async with await _client(timeout=30) as client:
        pole_id = await _resoudre_pole_crm(client)
        params = {"statut": statut} if statut else {}
        r = await _appel_protege(client, "GET", f"/api/poles/{pole_id}/crm", params=params)
    leads = _json_ou_erreur(r)
    items = [_resume_lead(l) for l in leads]
    par_statut: dict = {}
    for l in items:
        cell = par_statut.setdefault(l["statut"], {"nombre": 0, "valeur": 0})
        cell["nombre"] += 1
        cell["valeur"] += l["valeur"] or 0
    return {
        "total": len(items),
        "prospects": items,
        "pipeline": {
            "valeur_totale": sum((l["valeur"] or 0) for l in items),
            "par_statut": par_statut,
        },
    }


@app.post("/crm", summary="Ajouter un prospect (action)")
async def crm_creer(corps: dict = Body(...)):
    """Proxy authentifié → `POST /api/poles/{pole}/crm`. ACTION (écrit dans Forge).

    Entrée : ``{nom, entreprise?, email?, telephone?, statut?, valeur?, notes?}``.
    `statut` libre (défaut « prospect ») ; `valeur` = montant estimé de l'affaire (€).
    """
    nom = (corps.get("nom") or "").strip()
    if not nom:
        raise HTTPException(422, "Champ requis : 'nom'.")
    charge = {k: corps[k] for k in _CHAMPS_LEAD if corps.get(k) is not None}
    charge["nom"] = nom
    async with await _client(timeout=30) as client:
        pole_id = await _resoudre_pole_crm(client)
        r = await _appel_protege(client, "POST", f"/api/poles/{pole_id}/crm", json=charge)
    lead = _json_ou_erreur(r)
    return {"ok": True, **_resume_lead(lead),
            "message": f"Prospect « {nom} » ajouté (statut : {lead.get('statut')})."}


# ── Import en lot depuis la prospection geo (S169) ──────────────────────────────
# NB : cette route STATIQUE doit être déclarée AVANT « /crm/{lead_id} » — sinon FastAPI
# (qui matche par ordre de déclaration) capterait « /crm/import-lot » comme un lead_id.
def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _signatures(lead: dict) -> set[str]:
    """Empreintes de dé-doublonnage d'un prospect : l'email (fort) et le nom d'entreprise
    (repli). Deux prospects qui partagent l'un ou l'autre sont considérés identiques —
    l'import est ainsi ré-exécutable sans empiler des doublons."""
    sigs: set[str] = set()
    if lead.get("email"):
        sigs.add("email:" + _norm(lead["email"]))
    ent = lead.get("entreprise") or lead.get("nom")
    if ent:
        sigs.add("ent:" + _norm(ent))
    return sigs


def _prospect_vers_lead(p: dict, statut: str) -> dict:
    """Traduit un prospect enrichi par geo (geo_prospecter_lot) en lead CRM. Les infos de
    veille (site, NAF, commune, SIREN) enrichissent les `notes` — utiles pour démarcher."""
    ent = (p.get("entreprise") or p.get("nom") or "").strip()
    notes = []
    if p.get("site"):
        notes.append(f"Site : {p['site']}")
    if p.get("naf"):
        notes.append(f"NAF : {p['naf']}")
    if p.get("commune"):
        notes.append(f"Commune : {p['commune']}")
    if p.get("ref_externe"):
        notes.append(f"SIREN : {p['ref_externe']}")
    notes.append("Importé depuis la veille geo")
    if (p.get("notes") or "").strip():
        notes.append(p["notes"].strip())
    charge = {"nom": (p.get("nom") or ent), "entreprise": ent,
              "email": p.get("email"), "telephone": p.get("telephone"),
              "statut": statut, "notes": " · ".join(notes)}
    return {k: v for k, v in charge.items() if v is not None}


@app.post("/crm/import-lot", summary="Importer une liste de prospects dans le CRM (action)")
async def crm_importer_lot(corps: dict = Body(...)):
    """Verse EN LOT des prospects (issus de la veille geo, `geo_prospecter_lot`) dans le
    CRM. ACTION (écrit dans Forge). Dé-doublonne contre les prospects DÉJÀ présents et à
    l'intérieur du lot lui-même (par email, sinon par nom d'entreprise) ⇒ ré-exécutable
    sans créer de doublons. `statut` par défaut « à contacter » (première étape du
    pipeline de démarchage).

    Entrée : ``{prospects: [{nom|entreprise, email?, telephone?, site?, naf?, commune?,
    ref_externe?, notes?}], statut?}``.
    """
    prospects = corps.get("prospects")
    if not isinstance(prospects, list) or not prospects:
        raise HTTPException(422, "Champ requis : 'prospects' (liste non vide).")
    statut = (corps.get("statut") or "à contacter").strip() or "à contacter"
    async with await _client(timeout=60) as client:
        pole_id = await _resoudre_pole_crm(client)
        existants = _json_ou_erreur(
            await _appel_protege(client, "GET", f"/api/poles/{pole_id}/crm")) or []
        vus: set[str] = set()
        for lead in existants:
            vus |= _signatures(lead)
        crees, doublons, ignores = [], 0, 0
        for p in prospects:
            if not isinstance(p, dict):
                ignores += 1
                continue
            if not (p.get("nom") or p.get("entreprise")):
                ignores += 1                       # rien pour nommer le prospect
                continue
            sigs = _signatures(p)
            if sigs & vus:
                doublons += 1                      # déjà au CRM ou déjà vu dans ce lot
                continue
            lead = _json_ou_erreur(await _appel_protege(
                client, "POST", f"/api/poles/{pole_id}/crm",
                json=_prospect_vers_lead(p, statut)))
            crees.append(_resume_lead(lead))
            vus |= sigs
    return {"ok": True, "crees": len(crees), "doublons": doublons, "ignores": ignores,
            "statut": statut, "prospects": crees,
            "message": f"{len(crees)} prospect(s) ajouté(s) au CRM (statut « {statut} »), "
                       f"{doublons} doublon(s) ignoré(s)."}


@app.post("/crm/{lead_id}", summary="Mettre à jour un prospect / le faire avancer (action)")
async def crm_modifier(lead_id: str, corps: dict = Body(...)):
    """Proxy authentifié → `PATCH /api/crm/{id}`. ACTION (écrit dans Forge).

    Sert à faire avancer une affaire dans le pipeline (changer `statut`, ajuster
    `valeur`) ou corriger les coordonnées. Ne passe que les champs à changer.
    """
    champs = {k: corps[k] for k in _CHAMPS_LEAD if corps.get(k) is not None}
    if not champs:
        raise HTTPException(422, f"Au moins un champ à modifier parmi : {', '.join(_CHAMPS_LEAD)}.")
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "PATCH", f"/api/crm/{lead_id}", json=champs)
    lead = _json_ou_erreur(r)
    if not lead:
        raise HTTPException(404, "Prospect introuvable.")
    return {"ok": True, **_resume_lead(lead),
            "message": f"Prospect « {lead.get('nom')} » mis à jour (statut : {lead.get('statut')})."}


@app.delete("/crm/{lead_id}", summary="Supprimer un prospect (action)")
async def crm_supprimer(lead_id: str):
    """Proxy authentifié → `DELETE /api/crm/{id}`. ACTION (écrit dans Forge).

    Sert notamment à la **révocation/purge** d'un partage consenti (pont app→CRM,
    S24) : on retire du CRM du cabinet un prospect remonté depuis une app livrée.
    """
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "DELETE", f"/api/crm/{lead_id}")
    _json_ou_erreur(r)
    return {"ok": True, "message": "Prospect supprimé du CRM."}


# ── Paiement : encaissement en ligne via Stripe (S21) ───────────────────────────
#
# Proxy authentifié du router `stripe` du core (checkout RÉEL via SDK, webhook signé).
# La clé secrète vit dans le coffre chiffré de Forge (jamais via l'assistant). Contrat
# exposé en français : constater l'état (réel/mock), créer un lien de paiement, lire
# l'abonnement et l'historique. Même identité de service unique que facturation/crm.

# Plans payants exposés au lien de paiement (parité core).
_PLANS_PAIEMENT = {"starter", "pro", "enterprise"}


@app.get("/paiement/etat", summary="Stripe est-il réellement configuré ? (lecture)")
async def paiement_etat():
    """Proxy authentifié → `GET /api/stripe/etat`. Lecture seule.

    Dit honnêtement si l'encaissement est **réel** (clé test/live) ou **simulé**
    (mode mock). Ne renvoie jamais la clé, seulement un indice masqué.
    """
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "GET", "/api/stripe/etat")
    return _json_ou_erreur(r)


@app.get("/paiement/plans", summary="Plans d'abonnement et tarifs (lecture)")
async def paiement_plans():
    """Proxy authentifié → `GET /api/stripe/plans`. Lecture seule."""
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "GET", "/api/stripe/plans")
    return _json_ou_erreur(r)


@app.get("/paiement/abonnement", summary="Abonnement courant (lecture)")
async def paiement_abonnement():
    """Proxy authentifié → `GET /api/stripe/abonnement`. Lecture seule."""
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "GET", "/api/stripe/abonnement")
    return _json_ou_erreur(r)


@app.get("/paiement/paiements", summary="Historique des paiements (lecture)")
async def paiement_historique():
    """Proxy authentifié → `GET /api/stripe/payments`. Lecture seule."""
    async with await _client(timeout=15) as client:
        r = await _appel_protege(client, "GET", "/api/stripe/payments")
    paiements = _json_ou_erreur(r)
    return {"total": len(paiements) if isinstance(paiements, list) else 0, "paiements": paiements}


@app.post("/paiement/lien", summary="Créer un lien de paiement Stripe pour un plan (action)")
async def paiement_lien(corps: dict = Body(...)):
    """Proxy authentifié → `POST /api/stripe/checkout`. ACTION (crée une session Stripe).

    Entrée : ``{plan: 'starter'|'pro'|'enterprise'}``. Renvoie le lien de paiement
    (réel si Stripe est configuré, sinon un lien simulé clairement marqué `mock`).
    """
    plan = (corps.get("plan") or "").strip()
    if plan not in _PLANS_PAIEMENT:
        raise HTTPException(422, f"'plan' doit être l'un de : {', '.join(sorted(_PLANS_PAIEMENT))}.")
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "POST", "/api/stripe/checkout", json={"plan": plan})
    data = _json_ou_erreur(r)
    mode = data.get("mode", "inconnu")
    lien = data.get("checkoutUrl")
    suffixe = " (simulé — Stripe non configuré)" if mode == "mock" else ""
    return {
        "ok": True,
        "mode": mode,
        "plan": plan,
        "lien_paiement": lien,
        "session_id": data.get("sessionId"),
        "message": f"Lien de paiement pour le plan « {plan} »{suffixe} : {lien}",
    }


# ── Relances : emails de recouvrement des impayés (S22) ─────────────────────────
#
# Proxy authentifié du router `relances` du core (envoi de facture par email + moteur
# de relances J+7/15/30, anti-doublon). Même identité de service que facturation/crm.


@app.get("/relances/apercu", summary="Aperçu des relances dues (dry-run, lecture)")
async def relances_apercu():
    """Proxy authentifié → `GET /api/relances/impayes/apercu`. N'envoie rien."""
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "GET", "/api/relances/impayes/apercu")
    return _json_ou_erreur(r)


@app.post("/relances/executer", summary="Lancer les relances d'impayés dues (action)")
async def relances_executer():
    """Proxy authentifié → `POST /api/relances/impayes/executer`. ACTION (envoie des emails)."""
    async with await _client(timeout=60) as client:
        r = await _appel_protege(client, "POST", "/api/relances/impayes/executer")
    data = _json_ou_erreur(r)
    nb = data.get("nb_envoyees", 0)
    return {"ok": True, **data,
            "message": f"{nb} relance(s) envoyée(s) pour {data.get('montant_relance', 0)} € d'impayés."}


@app.get("/relances/journal", summary="Historique des relances envoyées (lecture)")
async def relances_journal():
    """Proxy authentifié → `GET /api/relances/journal`. Lecture seule."""
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "GET", "/api/relances/journal")
    return _json_ou_erreur(r)


@app.post("/facturation/{did}/envoyer", summary="Envoyer une facture au client par email (action)")
async def facturation_envoyer(did: str):
    """Proxy authentifié → `POST /api/facturation/{id}/envoyer`. ACTION (email + statut envoyée)."""
    async with await _client(timeout=30) as client:
        r = await _appel_protege(client, "POST", f"/api/facturation/{did}/envoyer")
    doc = _json_ou_erreur(r)
    return {"ok": True, "message": f"Facture envoyée à {doc.get('envoye_a')}.", **doc}
