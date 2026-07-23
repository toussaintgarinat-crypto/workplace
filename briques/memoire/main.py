"""Brique « memoire » — adaptateur entre Workplace et le projet Memory.

Le projet Memory (backend FastAPI + Postgres/pgvector, graphe de souvenirs avec
stages IPCRa, tiers et recherche hybride) est riche mais multi-espaces et
authentifié par JWT. Cette brique l'enveloppe derrière un **contrat simple** que
le reste de Workplace (le Cœur, Forge, Oria) peut consommer sans rien connaître
des espaces ni des tokens :

    GET    /sante
    POST   /retenir              {contenu, titre?, type?, wing?, room?, hall?, metadata?}
    GET    /rappeler?q=...        recherche hybride (texte+vecteur), avec score
    GET    /souvenirs?type=...    liste (filtrable par type/wing/room)
    GET    /taxonomy             comptes par type (pour les onglets/wings)
    DELETE /souvenir/{id}        supprime un souvenir

L'adaptateur gère une fois pour toutes : compte de service, connexion (JWT) et
**espace par défaut** (« Workplace »). Idempotent et tolérant au démarrage
différé du backend Memory.

Le backend Memory possède un `location` natif (wing/room/drawer) : on l'utilise
pour porter les rangements de Forge (wings IPCRa) et d'Oria (wing_user / salles).
"""

import asyncio
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MEMORY_API = os.environ.get("MEMORY_API", "http://memoire-backend:8000").rstrip("/")
EMAIL = os.environ.get("MEMOIRE_EMAIL", "service@workplace.local")
MOTDEPASSE = os.environ.get("MEMOIRE_PASSWORD", "workplace-memoire")
ESPACE = os.environ.get("MEMOIRE_ESPACE", "Workplace")
# Clé de service dédiée du Cœur (S186, motif agenda S182 / ecoute S184 / mail S185) : gage
# la surface /service par personne (X-User-Id) ET signe le jeton d'URL/cookie de la tuile
# dashboard (cf. _emettre_jeton/_verifier_jeton plus bas). Lue FRAÎCHE à chaque appel (pas
# une constante au chargement) — monkeypatchable en test, comme ECOUTE_KEY/MAIL_KEY. Sans
# clé configurée : mode ouvert (repli compte de service, comportement historique inchangé).

# Front React buildé (memory/frontend → /app/ui par le Dockerfile multi-stage).
# Absent en test/dev local : tout le service du front est alors gracieusement inerte.
UI_DIR = Path(os.environ.get("UI_DIR", "/app/ui"))

VERSION = "0.3.0"
app = FastAPI(title="Mémoire Workplace", version=VERSION)

# Session résolue paresseusement, protégée par un verrou. Le token de service est partagé ;
# les espaces (« Workplace » = solution, « Perso », …) sont résolus/créés à la demande et
# mémoïsés par nom → cloisonnement réel (le backend Memory isole les nœuds par space).
_session: dict = {"token": None}
_espaces: dict[str, str] = {}   # nom d'espace → espace_id
_verrou = asyncio.Lock()

# Comptes PAR PERSONNE (S186) : un vrai compte Memory dédié par utilisateur du cercle privé
# (au lieu du seul compte de service partagé ci-dessus), pour que « Perso » devienne un
# espace RÉELLEMENT privé (le backend Memory isole par space ET par appartenance — voir
# `_espace_id_personne`). Mémoïsés séparément du compte de service, verrou dédié.
_sessions_personne: dict[str, str] = {}          # utilisateur → jwt
_espaces_personne: dict[tuple[str, str], str] = {}  # (utilisateur, nom d'espace) → espace_id
_verrou_personnes = asyncio.Lock()

COOKIE_MEMOIRE = "memoire_utilisateur"


async def _token(client: httpx.AsyncClient) -> str:
    """Garantit le compte de service et renvoie un JWT (mémoïsé)."""
    if _session["token"]:
        return _session["token"]
    async with _verrou:
        if _session["token"]:
            return _session["token"]
        # 1) Inscription idempotente (400 = déjà inscrit → on ignore).
        try:
            await client.post(
                f"{MEMORY_API}/api/v1/auth/register",
                json={"email": EMAIL, "password": MOTDEPASSE, "display_name": "Workplace"},
            )
        except httpx.HTTPError:
            pass
        # 2) Connexion → JWT.
        r = await client.post(
            f"{MEMORY_API}/api/v1/auth/login",
            json={"email": EMAIL, "password": MOTDEPASSE},
        )
        r.raise_for_status()
        _session["token"] = r.json()["access_token"]
        return _session["token"]


async def _espace_id(client: httpx.AsyncClient, nom: str | None = None) -> str:
    """Renvoie l'id de l'espace `nom` (créé s'il n'existe pas). Défaut = espace solution."""
    nom = (nom or ESPACE).strip() or ESPACE
    if nom in _espaces:
        return _espaces[nom]
    # Résoudre le token AVANT de prendre _verrou (sinon double acquisition = deadlock).
    token = await _token(client)
    async with _verrou:
        if nom in _espaces:
            return _espaces[nom]
        entetes = {"Authorization": f"Bearer {token}"}
        r = await client.get(f"{MEMORY_API}/api/v1/spaces", headers=entetes)
        r.raise_for_status()
        espace = next((e for e in r.json() if e.get("name") == nom), None)
        if espace is None:
            desc = ("Mémoire de la solution Workplace" if nom == ESPACE
                    else f"Espace mémoire « {nom} »")
            r = await client.post(
                f"{MEMORY_API}/api/v1/spaces",
                headers=entetes,
                json={"name": nom, "description": desc},
            )
            r.raise_for_status()
            espace = r.json()
        _espaces[nom] = espace["id"]
        return _espaces[nom]


async def _token_personne(client: httpx.AsyncClient, utilisateur: str) -> str:
    """Garantit un compte Memory DÉDIÉ à `utilisateur` (créé si besoin, mot de passe dérivé
    déterministe — pas de secret par personne à gérer) et renvoie son JWT (mémoïsé).

    Motif `_token` (compte de service) répliqué par personne. La ressemblance est
    volontaire : quand le backend Memory isole par space+appartenance, donner à chaque
    personne SON compte est la façon la plus simple d'obtenir une isolation réelle, sans
    réinventer un modèle de permissions."""
    if utilisateur in _sessions_personne:
        return _sessions_personne[utilisateur]
    async with _verrou_personnes:
        if utilisateur in _sessions_personne:
            return _sessions_personne[utilisateur]
        email = f"{utilisateur}@workplace.local"
        motdepasse = hashlib.sha256(f"{MOTDEPASSE}:{utilisateur}".encode()).hexdigest()
        try:
            await client.post(
                f"{MEMORY_API}/api/v1/auth/register",
                json={"email": email, "password": motdepasse, "display_name": utilisateur},
            )
        except httpx.HTTPError:
            pass
        r = await client.post(
            f"{MEMORY_API}/api/v1/auth/login",
            json={"email": email, "password": motdepasse},
        )
        r.raise_for_status()
        _sessions_personne[utilisateur] = r.json()["access_token"]
    # Hors du verrou personne (comme _espace_id vs _token) : _assurer_membre_workplace
    # prend son PROPRE verrou (_verrou, compte de service) — jamais les deux à la fois.
    await _assurer_membre_workplace(client, email)
    return _sessions_personne[utilisateur]


async def _assurer_membre_workplace(client: httpx.AsyncClient, email_personne: str) -> None:
    """Invite `email_personne` dans l'espace PARTAGÉ Workplace s'il n'y est pas déjà.

    Idempotent : un 409 (déjà membre) ou toute erreur HTTP est tolérée sans bloquer — la
    pire conséquence d'un échec transitoire est que la personne ne voit pas encore la
    mémoire partagée, jamais un blocage de son espace privé."""
    try:
        token_service = await _token(client)
        espace_id = await _espace_id(client, None)
        await client.post(
            f"{MEMORY_API}/api/v1/spaces/{espace_id}/invite",
            headers={"Authorization": f"Bearer {token_service}"},
            json={"email": email_personne, "role": "member"},
        )
    except httpx.HTTPError:
        pass


async def _espace_id_personne(client: httpx.AsyncClient, jeton_personne: str,
                              utilisateur: str, nom: str) -> str:
    """Comme `_espace_id`, mais résolu/créé sous le compte de LA PERSONNE — elle en devient
    propriétaire, le compte de service n'y a PAS accès (isolation réelle, pas un simple
    nommage). `GET /spaces` du backend Memory ne renvoie QUE les espaces dont l'appelant
    est membre : on ne peut donc PAS réutiliser `_espace_id` (résolution côté service)."""
    cle = (utilisateur, nom)
    if cle in _espaces_personne:
        return _espaces_personne[cle]
    async with _verrou_personnes:
        if cle in _espaces_personne:
            return _espaces_personne[cle]
        entetes = {"Authorization": f"Bearer {jeton_personne}"}
        r = await client.get(f"{MEMORY_API}/api/v1/spaces", headers=entetes)
        r.raise_for_status()
        espace = next((e for e in r.json() if e.get("name") == nom), None)
        if espace is None:
            r = await client.post(
                f"{MEMORY_API}/api/v1/spaces", headers=entetes,
                json={"name": nom, "description": f"Espace privé de {utilisateur}"},
            )
            r.raise_for_status()
            espace = r.json()
        _espaces_personne[cle] = espace["id"]
        return _espaces_personne[cle]


async def _resoudre_espace(client: httpx.AsyncClient, espace_brut: str | None,
                           utilisateur: str) -> tuple[str, str]:
    """Résout `(espace_id, jwt à utiliser)` pour un appel de `utilisateur`.

    Le mot-clé ``perso`` garde sa branche dédiée EXACTE (S186, inchangée) : nom d'espace
    ``Perso-<utilisateur>``, casse figée.

    Tout AUTRE nom custom (ni ``None``/``"solution"``, ni ``"perso"``) devient lui aussi
    personnellement isolé (S193) dès qu'un ``utilisateur`` RÉEL est résolu (≠
    ``UTILISATEUR_DEFAUT`` — c'est-à-dire qu'un vrai ``X-User-Id`` a été transmis) : espace
    ``<nom>-<utilisateur>``, compte de LA personne. Généralisation du motif « perso », pour
    que veille-prospection/veille-info isolent leur espace "veille" par personne sans
    dupliquer la mécanique.

    Sans ``utilisateur`` réel (mode service/mono-user, ex. Forge ``forge-org-*``,
    ``transcription``) : comportement INCHANGÉ, espace partagé sous le compte de service —
    aucun appelant actuel ne transmet ``X-User-Id`` pour un espace custom, donc ce
    changement est rétrocompatible par construction (vérifié par test)."""
    if (espace_brut or "").strip().lower() == "perso":
        if utilisateur == UTILISATEUR_DEFAUT:
            return await _espace_id(client, "Perso"), await _token(client)
        jeton_personne = await _token_personne(client, utilisateur)
        nom = f"Perso-{utilisateur}"
        return await _espace_id_personne(client, jeton_personne, utilisateur, nom), jeton_personne
    nom = _normaliser_espace(espace_brut)
    if nom is not None and utilisateur != UTILISATEUR_DEFAUT:
        jeton_personne = await _token_personne(client, utilisateur)
        nom_personne = f"{nom}-{utilisateur}"
        return (await _espace_id_personne(client, jeton_personne, utilisateur, nom_personne),
                jeton_personne)
    return await _espace_id(client, nom), await _token(client)


def _invalider_jetons(utilisateur: str) -> None:
    """Force une ré-authentification au prochain appel : vide le jeton mis en cache,
    service ET personne (sans savoir lequel des deux a expiré — revalider les deux est
    idempotent et sans coût notable). Sans ce filet, un jeton mémoïsé qui expire côté
    Memory casse SILENCIEUSEMENT tout appelant de cette brique jusqu'à un redémarrage
    manuel du conteneur — bug constaté en prod le 2026-07-23 (jeton de service resté
    ~30h en cache, jamais revalidé ni rafraîchi par `_token`/`_token_personne`, qui ne
    font que renvoyer la valeur mémoïsée sans vérifier qu'elle est toujours acceptée par
    Memory)."""
    _session["token"] = None
    _sessions_personne.pop(utilisateur, None)


async def _appel_avec_retry(client: httpx.AsyncClient, utilisateur: str,
                            espace_brut: str | None, faire_appel):
    """Résout `(espace_id, jeton)` pour `utilisateur`/`espace_brut`, puis exécute
    `faire_appel(espace_id, jeton) -> httpx.Response`. Si Memory répond 401 (jeton
    mémoïsé expiré), invalide le cache et réessaie UNE fois avec un jeton frais avant
    d'abandonner — voir `_invalider_jetons`."""
    espace_id, jeton = await _resoudre_espace(client, espace_brut, utilisateur)
    r = await faire_appel(espace_id, jeton)
    if r.status_code == 401:
        _invalider_jetons(utilisateur)
        espace_id, jeton = await _resoudre_espace(client, espace_brut, utilisateur)
        r = await faire_appel(espace_id, jeton)
    return espace_id, r


# ── Identité de l'appelant (S186, motif ecoute S184 : X-User-Id gagé par MEMOIRE_KEY) ──

UTILISATEUR_DEFAUT = "perso"


def _presentee(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    return x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None


def _identite_service(x_api_key: Optional[str] = Header(None),
                      authorization: Optional[str] = Header(None),
                      x_user_id: Optional[str] = Header(None)) -> str:
    """Identité pour les routes du contrat (`/retenir`, `/rappeler`…) : `MEMOIRE_KEY`
    configurée ⇒ seul le Cœur (qui la détient) peut emprunter `X-User-Id`. Sans clé
    configurée (dev/mono-user) : mode ouvert, `X-User-Id` honoré tel quel s'il est fourni."""
    cle = os.environ.get("MEMOIRE_KEY")
    if cle and _presentee(x_api_key, authorization) != cle:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or UTILISATEUR_DEFAUT


# ── Jeton signé Cœur→mémoire (S186) : dit QUI ouvre l'onglet Mémoire du dashboard, sans
# exposer MEMOIRE_KEY au navigateur. HMAC (pas de chiffrement : l'identité n'est pas
# confidentielle, seule l'INTÉGRITÉ compte — empêche un utilisateur connecté de fabriquer
# le jeton d'un autre). Même secret que la surface /service : double emploi assumé, motif
# déjà utilisé pour AGENDA_KEY/MAIL_KEY comme gage de confiance du Cœur.

def _secret_jeton() -> bytes:
    return (os.environ.get("MEMOIRE_KEY") or "").encode()


def _emettre_jeton(utilisateur: str, ttl: int = 120) -> str:
    expire = int(time.time()) + ttl
    message = f"{utilisateur}:{expire}"
    signature = hmac.new(_secret_jeton(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def _verifier_jeton(jeton: Optional[str]) -> Optional[str]:
    if not jeton or not _secret_jeton():
        return None
    try:
        utilisateur, expire, signature = jeton.rsplit(":", 2)
        expire_i = int(expire)
    except ValueError:
        return None
    message = f"{utilisateur}:{expire}"
    attendue = hmac.new(_secret_jeton(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, attendue) or time.time() > expire_i:
        return None
    return utilisateur


def _identite_navigateur(request: Request) -> Optional[str]:
    """QUI ouvre l'onglet Mémoire : jeton d'URL (1re navigation, posé par le Cœur) en
    priorité, sinon le cookie déjà posé par une navigation précédente. `None` si ni l'un ni
    l'autre — repli sur le compte de service (comportement historique, mono-tenant)."""
    return (_verifier_jeton(request.query_params.get("m"))
            or _verifier_jeton(request.cookies.get(COOKIE_MEMOIRE)))


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20)


# ── Modèles ──────────────────────────────────────────────────────────────────

# Types de nœuds valides côté Memory (enum NodeType). « input » = entrée IPCRa.
TYPES_VALIDES = {"input", "projet", "casquette", "ressource", "archive"}


def _type_valide(t: str | None) -> str:
    return t if t in TYPES_VALIDES else "input"


class Souvenir(BaseModel):
    contenu: str
    titre: str | None = None
    type: str = "input"
    wing: str | None = None          # rangement (défaut : = type) — location.wing côté Memory
    room: str | None = None          # sous-rangement (défaut : « general ») — location.room
    hall: str | None = None          # méta libre (hall_events/hall_facts…) → frontmatter
    metadata: dict | None = None     # méta libre supplémentaire → frontmatter
    espace: str | None = None        # None → espace solution (« Workplace »)


# ── Contrat ──────────────────────────────────────────────────────────────────

@app.get("/sante")
async def sante():
    """OK si le backend Memory répond et que la session de service est résolue."""
    try:
        async with await _client() as client:
            await _espace_id(client)  # résout token + espace solution
        return {"statut": "ok", "service": "memoire", "version": VERSION,
                "espaces": _espaces}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Backend Memory indisponible : {e}")


def _normaliser_espace(espace: str | None) -> str | None:
    """Normalise l'espace envoyé par le manifest : 'solution'→None (défaut), reste (custom
    Forge/Oria) passé tel quel. Le mot-clé 'perso' n'est PAS géré ici (S186) : il a besoin de
    savoir QUI appelle pour construire un nom d'espace par personne — voir `_resoudre_espace`."""
    if not espace:
        return None
    low = espace.strip().lower()
    if low == "solution":
        return None
    return espace  # valeur brute pour les espaces custom (et 'perso', intercepté en amont)


@app.post("/retenir", summary="Mémoriser un souvenir")
async def retenir(s: Souvenir, utilisateur: str = Depends(_identite_service)):
    titre = (s.titre or s.contenu[:60] or "souvenir").strip()
    type_ = _type_valide(s.type)
    # Rangement : par défaut le wing reflète le type (vue Forge = wings IPCRa) ;
    # Oria fournit un wing/room explicites (wing_user / salles thématiques).
    wing = (s.wing or type_).strip() or type_
    room = (s.room or "general").strip() or "general"
    frontmatter = dict(s.metadata or {})
    if s.hall:
        frontmatter["hall"] = s.hall
    # Le backend Memory ne persiste pas toujours `location` à la création : on garde
    # donc wing/room AUSSI dans le frontmatter (source de vérité fiable au relire).
    frontmatter["wing"] = wing
    frontmatter["room"] = room
    corps = {
        "type": type_,
        "title": titre,
        "content_md": s.contenu,
        "location": {"wing": wing, "room": room},
        "frontmatter": frontmatter,
    }
    async with await _client() as client:
        async def _appel(espace_id: str, jeton: str):
            return await client.post(
                f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
                json=corps,
                headers={"Authorization": f"Bearer {jeton}"},
            )
        _, r = await _appel_avec_retry(client, utilisateur, s.espace, _appel)
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        n = r.json()
    # wing/room : valeurs envoyées (Memory n'écho pas toujours location dans la réponse).
    return {"retenu": True, "id": n["id"], "titre": n["title"], "type": n["type"],
            "wing": wing, "room": room}


@app.get("/rappeler", summary="Retrouver des souvenirs (recherche hybride)")
async def rappeler(q: str = "", limite: int = 8, type: str | None = None,
                   espace: str | None = None,
                   utilisateur: str = Depends(_identite_service)):
    params: dict = {"q": q, "limit": limite}
    if type:
        params["type"] = type
    async with await _client() as client:
        async def _appel(espace_id: str, jeton: str):
            return await client.get(
                f"{MEMORY_API}/api/v1/spaces/{espace_id}/search",
                params=params,
                headers={"Authorization": f"Bearer {jeton}"},
            )
        _, r = await _appel_avec_retry(client, utilisateur, espace, _appel)
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        resultats = r.json()
    souvenirs = [
        {
            "id": x.get("id"),
            "titre": x.get("title"),
            "extrait": (x.get("content_md") or "")[:280],
            "type": x.get("type"),
            "score": x.get("score", 0),
        }
        for x in resultats
    ]
    return {"requete": q, "total": len(souvenirs), "souvenirs": souvenirs}


@app.get("/souvenirs", summary="Lister les souvenirs récents")
async def souvenirs(limite: int = 20, type: str | None = None,
                    wing: str | None = None, room: str | None = None,
                    espace: str | None = None,
                    utilisateur: str = Depends(_identite_service)):
    params: dict = {"limit": limite}
    if type:
        params["type"] = type
    if wing:
        params["wing"] = wing
    if room:
        params["room"] = room
    async with await _client() as client:
        async def _appel(espace_id: str, jeton: str):
            return await client.get(
                f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes",
                params=params,
                headers={"Authorization": f"Bearer {jeton}"},
            )
        _, r = await _appel_avec_retry(client, utilisateur, espace, _appel)
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        noeuds = r.json()

    def _vue(n: dict) -> dict:
        loc = n.get("location") or {}
        fm = n.get("frontmatter") or {}
        return {
            "id": n.get("id"), "titre": n.get("title"),
            "contenu": n.get("content_md"), "type": n.get("type"),
            # location d'abord (si Memory l'a persistée), sinon repli sur le frontmatter.
            "wing": loc.get("wing") or fm.get("wing"),
            "room": loc.get("room") or fm.get("room"),
            "metadata": fm,
            "stage": n.get("ipcra_stage"), "tier": n.get("storage_tier"),
        }

    return {"total": len(noeuds), "souvenirs": [_vue(n) for n in noeuds]}


@app.get("/taxonomy", summary="Comptes par type (pour les onglets/wings)")
async def taxonomy(espace: str | None = None,
                   utilisateur: str = Depends(_identite_service)):
    async with await _client() as client:
        # /stats est protégé (check_space_access) → le jwt renvoyé par _resoudre_espace
        # (service pour un espace partagé, personne pour son "Perso") EST le bon acteur.
        async def _appel(espace_id: str, jeton: str):
            return await client.get(
                f"{MEMORY_API}/api/v1/spaces/{espace_id}/stats",
                headers={"Authorization": f"Bearer {jeton}"},
            )
        _, r = await _appel_avec_retry(client, utilisateur, espace, _appel)
        if r.status_code >= 400:
            raise HTTPException(502, f"Memory: {r.text}")
        stats = r.json()
    return {
        "total": stats.get("total_nodes", 0),
        "par_type": stats.get("by_type", {}),
        "par_stage": stats.get("by_stage", {}),
    }


@app.delete("/souvenir/{souvenir_id}", summary="Supprimer un souvenir")
async def supprimer(souvenir_id: str, espace: str | None = None,
                    utilisateur: str = Depends(_identite_service)):
    async with await _client() as client:
        async def _appel(espace_id: str, jeton: str):
            return await client.delete(
                f"{MEMORY_API}/api/v1/spaces/{espace_id}/nodes/{souvenir_id}",
                headers={"Authorization": f"Bearer {jeton}"},
            )
        _, r = await _appel_avec_retry(client, utilisateur, espace, _appel)
        if r.status_code >= 400 and r.status_code != 404:
            raise HTTPException(502, f"Memory: {r.text}")
    return {"supprime": True, "id": souvenir_id}


# ── Front React (S108) ─────────────────────────────────────────────────────────
# La brique sert le vrai front du projet Memory (memory/frontend, buildé dans /app/ui)
# et reverse-proxy /api/v1 vers le backend Memory interne. Le front parle à /api/v1 en
# relatif → tout est same-origin (pas de CORS). L'auth est injectée côté serveur : le
# proxy force le JWT de service sur chaque appel, et l'index pré-remplit localStorage
# (auth_token + active_space_id) pour passer le garde RequireAuth sans écran de connexion.

# En-têtes hop-by-hop : ne JAMAIS recopier de/vers le client (gérés par le transport).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length", "host",
}


@app.api_route(
    "/api/v1/{chemin:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_api(chemin: str, request: Request):
    """Relaie /api/v1/* vers le backend Memory interne en forçant l'auth — celle de LA
    PERSONNE qui a ouvert l'onglet (S186, cookie/jeton posé par `spa()`) si elle est
    identifiée, sinon celle du compte de service (comportement historique, mono-tenant).

    On IGNORE l'Authorization éventuel du front (jeton injecté, peut-être périmé) et on
    pose toujours un JWT frais, RE-RÉSOLU À CHAQUE APPEL — pas de staleness possible, et
    l'identité vient TOUJOURS du cookie signé du Cœur, jamais d'un en-tête du navigateur.
    """
    utilisateur = _identite_navigateur(request)
    corps = await request.body()
    entetes = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }
    async with await _client() as client:
        jeton = await (_token_personne(client, utilisateur) if utilisateur else _token(client))
        entetes["Authorization"] = f"Bearer {jeton}"
        amont = await client.request(
            request.method,
            f"{MEMORY_API}/api/v1/{chemin}",
            params=dict(request.query_params),
            content=corps,
            headers=entetes,
        )
    sortie = {
        k: v for k, v in amont.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    return Response(content=amont.content, status_code=amont.status_code,
                    headers=sortie, media_type=amont.headers.get("content-type"))


# Assets statiques du build Vite (montés seulement si le front est présent).
if (UI_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(UI_DIR / "assets")), name="assets")


def _type_mime(nom: str) -> str:
    import mimetypes
    return mimetypes.guess_type(nom)[0] or "application/octet-stream"


async def _index_injecte(utilisateur: Optional[str]) -> str:
    """index.html du front avec un <script> qui pré-remplit localStorage (auth + espace).

    `utilisateur` identifié (S186, cookie/jeton du Cœur) ⇒ SON compte + la mémoire partagée
    Workplace en espace de départ (elle est déjà membre, cf. `_token_personne`). Sinon
    (comportement historique) : compte de service, mono-tenant."""
    index = UI_DIR / "index.html"
    if not index.is_file():
        return ("<!doctype html><meta charset=utf-8><title>Mémoire</title>"
                "<p>Front non buildé (image construite sans le stage Node ?).</p>")
    html = index.read_text(encoding="utf-8")
    async with await _client() as client:
        if utilisateur:
            token = await _token_personne(client, utilisateur)
        else:
            token = await _token(client)
        # L'id d'espace Workplace est une simple valeur (même UUID quel que soit qui la
        # résout) : toujours via le compte de service, garanti membre/propriétaire, pour ne
        # jamais risquer une création en double si l'invite d'une personne est très récente.
        espace_id = await _espace_id(client)
    boot = (
        "<script>try{"
        f"localStorage.setItem('auth_token',{token!r});"
        f"localStorage.setItem('active_space_id',{espace_id!r});"
        "}catch(e){}</script>"
    )
    return html.replace("</head>", boot + "</head>", 1)


@app.get("/", include_in_schema=False)
async def racine():
    return RedirectResponse("/memory")


@app.get("/{chemin:path}", include_in_schema=False)
async def spa(chemin: str, request: Request):
    """Fallback SPA : toute route front (/memory, /memory/graph, …) rend l'index injecté.

    Déclaré en DERNIER : le contrat (/sante, /retenir…) et /api/v1 sont matchés avant.
    Un fichier statique racine présent (favicon.svg…) est servi tel quel.

    Identité (S186) : jeton `?m=` (posé par le Cœur dans l'URL de la tuile, 1re navigation)
    ou cookie déjà posé par une navigation précédente. Un jeton d'URL valide RAFRAÎCHIT le
    cookie (la personne peut rouvrir l'onglet plus tard sans repasser par le dashboard)."""
    if chemin and UI_DIR.is_dir():
        cible = UI_DIR / chemin
        if cible.is_file() and cible.resolve().is_relative_to(UI_DIR.resolve()):
            return Response(content=cible.read_bytes(), media_type=_type_mime(cible.name))
    jeton_url = request.query_params.get("m")
    utilisateur = _verifier_jeton(jeton_url) or _verifier_jeton(request.cookies.get(COOKIE_MEMOIRE))
    reponse = HTMLResponse(await _index_injecte(utilisateur))
    if jeton_url and utilisateur:
        reponse.set_cookie(COOKIE_MEMOIRE, _emettre_jeton(utilisateur, ttl=8 * 3600),
                           max_age=8 * 3600, httponly=True, samesite="lax")
    return reponse
