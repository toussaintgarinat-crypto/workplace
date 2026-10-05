"""Modèles LLM ajoutés depuis ⚙ Cerveau, servis EN BASE par LiteLLM (S240).

Avant S240, ajouter un modèle (ex. un 2e modèle Groq) imposait d'éditer
`briques/gateway/litellm_config.yaml` puis de recréer la Gateway. LiteLLM v1.86.2 gère des
modèles en base à chaud (`/model/new`, `/model/delete`, `model_info.db_model`), déjà utilisé
par gateway-sync pour `free/*` et `kilo/*` : on s'en sert ici pour un troisième préfixe,
`perso/<fournisseur>/<id>`, qui ne collisionne ni avec le YAML ni avec gateway-sync.

Règles de sécurité (le pourquoi) :
- **catalogue serveur** : l'appelant ne fournit que `fournisseur` + identifiant. Jamais
  d'`api_base` ni de clé libres — sinon on pourrait faire envoyer une clé existante de la
  Gateway vers un serveur arbitraire ;
- **aucun `api_key` envoyé à LiteLLM** : pour un modèle EN BASE, LiteLLM v1.86.2 ne résout
  PAS `os.environ/XXX` (prouvé : la chaîne littérale partait en `Authorization: Bearer
  os.environ/MISTRAL_API_KEY`). Sans `api_key`, chaque préfixe de fournisseur lit sa
  variable par défaut dans l'environnement de la Gateway (prouvé aussi) — celle que
  ⚙ Cerveau écrit déjà. Bonus : une clé changée est prise en compte sans toucher la base ;
- **testé avant d'être gardé** : une complétion courte ; échec ou délai → le modèle est
  retiré aussitôt, jamais laissé cassé en base ;
- **on ne retire que les siens** : préfixe `perso/` ET `db_model` vrai.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx

import config_assistant

logger = logging.getLogger(__name__)

PREFIXE_PERSO = "perso/"
# Délai du test de complétion : court, pour ne pas figer le panneau sur un fournisseur qui
# pend. Côté LiteLLM (`timeout` de la requête) un peu sous celui du client httpx, pour que
# ce soit LiteLLM qui coupe et renvoie une erreur lisible.
DELAI_TEST_S = 20
_TIMEOUT_API = 15.0

# Segments séparés par « / », chacun commence par un alphanumérique ASCII (exclut `..`,
# `//`, `/` en tête ou en fin, espaces, schémas d'URL `http:` + `//`).
_RE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]*(/[A-Za-z0-9][A-Za-z0-9._:@-]*)*", re.ASCII)
_LONGUEUR_MAX = 120


class ValeurInvalide(ValueError):
    """Entrée refusée (→ 400)."""


class Conflit(Exception):
    """Le modèle existe déjà / est utilisé (→ 409)."""


class Introuvable(Exception):
    """Aucun modèle retirable sous ce nom (→ 404)."""


class GatewayInjoignable(Exception):
    """La Gateway (API d'administration LiteLLM) ne répond pas (→ 502)."""


def _catalogue() -> dict[str, dict]:
    return {f["id"]: f for f in config_assistant.FOURNISSEURS_CLES if f.get("prefixe_litellm")}


def fournisseurs() -> list[dict]:
    """Fournisseurs dont on peut ajouter un modèle — pour le front (ni env ni api_base)."""
    etat = {f["id"]: f["definie"] for f in config_assistant.cles_fournisseurs_etat()}
    return [{"id": f["id"], "label": f["label"], "cle_definie": etat.get(f["id"], False)}
            for f in _catalogue().values()]


def valider_identifiant(ident: str) -> str:
    if not isinstance(ident, str) or len(ident) > _LONGUEUR_MAX or not _RE_ID.fullmatch(ident):
        raise ValeurInvalide(
            "Identifiant de modèle invalide (lettres, chiffres, « . _ : @ - », segments "
            f"séparés par « / », {_LONGUEUR_MAX} caractères au plus).")
    return ident


def params_litellm(fournisseur: str, ident: str) -> dict:
    """`litellm_params` d'un modèle du catalogue : le seul champ est `model`, à dessein
    (pas de clé, pas d'`api_base` — cf. docstring du module)."""
    f = _catalogue().get(fournisseur)
    if not f:
        raise ValeurInvalide(f"Fournisseur inconnu ou non ajoutable : {fournisseur!r}.")
    return {"model": f["prefixe_litellm"] + valider_identifiant(ident)}


def nom_perso(fournisseur: str, ident: str) -> str:
    return f"{PREFIXE_PERSO}{fournisseur}/{ident}"


def analyser_nom_perso(nom: str) -> tuple[str, str] | None:
    """`perso/groq/x/y` → ("groq", "x/y") ; None si ce n'est pas un nom `perso/` valide."""
    if not nom.startswith(PREFIXE_PERSO):
        return None
    reste = nom[len(PREFIXE_PERSO):]
    fournisseur, _, ident = reste.partition("/")
    if fournisseur not in _catalogue() or not ident:
        return None
    try:
        valider_identifiant(ident)
    except ValeurInvalide:
        return None
    return fournisseur, ident


# ── API d'administration LiteLLM ─────────────────────────────────────────────

def _entetes() -> dict:
    # GATEWAY_KEY du Cœur = LITELLM_MASTER_KEY (vérifié sur le HP) : seule la clé maîtresse
    # ouvre /model/new et /model/delete.
    return {"Authorization": f"Bearer {config_assistant.GATEWAY_KEY}"}


async def deploiements() -> list[dict]:
    """[{nom, id, db, model}] de tous les déploiements servis (YAML + base).

    `model` (préfixe LiteLLM + id amont) sert à la Forge pour savoir si `forge/defaut` pointe
    déjà sur le bon modèle ; les autres `litellm_params` (clés…) ne sortent jamais d'ici."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_API) as c:
            r = await c.get(f"{config_assistant.GATEWAY_URL}/model/info", headers=_entetes())
            r.raise_for_status()
            donnees = r.json().get("data", [])
    except httpx.HTTPError as e:
        raise GatewayInjoignable(f"Gateway injoignable ({type(e).__name__}).") from e
    sortie = []
    for m in donnees:
        info = m.get("model_info") or {}
        sortie.append({"nom": m.get("model_name", ""), "id": info.get("id", ""),
                       "db": info.get("db_model") is True,
                       "model": (m.get("litellm_params") or {}).get("model", "")})
    return sortie


async def creer(nom: str, params: dict) -> str:
    """Crée un déploiement en base ; renvoie son id LiteLLM."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_API) as c:
            r = await c.post(f"{config_assistant.GATEWAY_URL}/model/new", headers=_entetes(),
                             json={"model_name": nom, "litellm_params": params})
            r.raise_for_status()
            return r.json().get("model_id") or (r.json().get("model_info") or {}).get("id", "")
    except httpx.HTTPError as e:
        raise GatewayInjoignable(f"Création de {nom} refusée par la Gateway ({type(e).__name__}).") from e


async def supprimer(id_deploiement: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_API) as c:
            r = await c.post(f"{config_assistant.GATEWAY_URL}/model/delete", headers=_entetes(),
                             json={"id": id_deploiement})
            r.raise_for_status()
    except httpx.HTTPError as e:
        raise GatewayInjoignable(f"Retrait refusé par la Gateway ({type(e).__name__}).") from e


async def tester(nom: str) -> tuple[bool, str]:
    """Complétion réelle, courte, SANS cache ni repli : appel direct à la Gateway (pas
    `llm_pipeline`, dont le cache sémantique pourrait renvoyer un « pong » d'un autre
    modèle et faire passer un modèle cassé pour sain)."""
    corps = {"model": nom, "messages": [{"role": "user", "content": "ping"}],
             "max_tokens": 5, "timeout": DELAI_TEST_S - 2, "num_retries": 0,
             # Sans repli : pour `forge/defaut`, un modèle en panne passerait sinon pour sain
             # en étant servi par `gratuit/*` (router.py de LiteLLM lit ce champ).
             "disable_fallbacks": True}
    try:
        async with httpx.AsyncClient(timeout=DELAI_TEST_S) as c:
            r = await c.post(f"{config_assistant.GATEWAY_URL}/v1/chat/completions",
                             headers=_entetes(), json=corps)
    except httpx.TimeoutException:
        return False, f"Délai dépassé ({DELAI_TEST_S} s) : le fournisseur ne répond pas."
    except httpx.HTTPError as e:
        return False, f"Gateway injoignable ({type(e).__name__})."
    if r.status_code == 200:
        return True, "Le modèle répond."
    try:
        msg = (r.json().get("error") or {}).get("message") or r.text
    except ValueError:
        msg = r.text
    return False, f"HTTP {r.status_code} : {str(msg)[:300]}"


# ── Opérations exposées au router ────────────────────────────────────────────

def _origine(nom: str, db: bool) -> str:
    if nom.startswith(config_assistant.ALIAS_RESERVES_FORGE):
        return "forge"
    if nom.startswith(PREFIXE_PERSO) and db:
        return "perso"
    if nom.startswith(("free/", "kilo/")):
        return "gratuit"
    return "yaml" if not db else "base"


async def lister() -> list[dict]:
    """Modèles servis, dédupliqués par nom, avec leur origine — sans aucun paramètre."""
    vus: dict[str, dict] = {}
    for d in await deploiements():
        if d["nom"] in vus:
            continue
        origine = _origine(d["nom"], d["db"])
        vus[d["nom"]] = {"nom": d["nom"], "origine": origine, "retirable": origine == "perso"}
    return sorted(vus.values(), key=lambda m: m["nom"])


# Verrou UNIQUE des écritures de modèles en base (revue S240, M5/M6) : ajouter, retirer,
# re-pointer la Forge et la veille. Sans lui, deux ajouts simultanés passaient tous deux le
# contrôle de doublon, et un retrait pouvait s'intercaler pendant qu'on basculait la Forge
# sur le modèle retiré. Un ajout tient le verrou pendant son test (≤ 20 s) : acceptable,
# ces opérations sont humaines et rares.
_verrou_forge = asyncio.Lock()


async def _retirer_par_nom(nom: str) -> bool:
    """Retire tout déploiement EN BASE portant `nom` ; best-effort, True si plus rien ne reste.

    Sert après un `/model/new` en échec ou en délai dépassé : LiteLLM a pu créer le modèle
    alors que sa réponse s'est perdue (revue S240, M1) — l'id est alors inconnu, le nom non."""
    try:
        for d in await deploiements():
            if d["nom"] == nom and d["db"] and d["id"]:
                await supprimer(d["id"])
        return True
    except GatewayInjoignable:
        return False


async def ajouter(fournisseur: str, ident: str) -> dict:
    """Crée `perso/<fournisseur>/<id>` en base, le teste, le retire si le test échoue."""
    ident = (ident or "").strip()
    params = params_litellm((fournisseur or "").strip(), ident)
    nom = nom_perso(fournisseur.strip(), ident)
    async with _verrou_forge:
        return await _ajouter(nom, params)


async def _ajouter(nom: str, params: dict) -> dict:
    if any(d["nom"] == nom for d in await deploiements()):
        raise Conflit(f"« {nom} » est déjà servi par la Gateway.")
    try:
        await creer(nom, params)
    except GatewayInjoignable:
        await _retirer_par_nom(nom)
        raise
    ok, detail = False, "Test interrompu."
    try:
        ok, detail = await tester(nom)
    finally:
        # `finally` : même une exception inattendue pendant le test ne laisse pas en base un
        # modèle jamais validé. Retrait PAR NOM (pas par l'id renvoyé) : couvre aussi un
        # doublon créé par une requête rejouée.
        if not ok and not await _retirer_par_nom(nom):
            detail += f" ⚠ Le retrait a échoué : « {nom} » reste en base, retire-le à la main."
    return {"ok": ok, "nom": nom, "detail": detail}


async def retirer(nom: str) -> dict:
    """Retire tous les déploiements `perso/*` EN BASE portant ce nom."""
    if analyser_nom_perso(nom or "") is None:
        raise ValeurInvalide("Seuls les modèles que tu as ajoutés (perso/…) peuvent être retirés.")
    async with _verrou_forge:
        return await _retirer(nom)


async def _retirer(nom: str) -> dict:
    conf = config_assistant.charger()
    # Un modèle en service dans la cascade du Cœur ne disparaît pas sous ses pieds : on
    # demande d'abord d'en choisir un autre (la cascade survivrait, mais en silence).
    for cle, libelle in (("model", "tête de l'assistant"), ("repli_payant", "repli payant"),
                         ("repli_souverain", "repli souverain")):
        if (conf.get(cle) or "").strip() == nom:
            raise Conflit(f"« {nom} » est la {libelle} : choisis-en d'abord un autre.")
    if (conf.get("forge_modele") or "").strip() == nom:
        raise Conflit(f"« {nom} » est le modèle de la Forge : choisis-en d'abord un autre.")
    ids = [d["id"] for d in await deploiements() if d["nom"] == nom and d["db"] and d["id"]]
    if not ids:
        raise Introuvable(f"Aucun modèle « {nom} » ajouté depuis ⚙ Cerveau.")
    for i in ids:
        await supprimer(i)
    return {"ok": True, "nom": nom, "retires": len(ids)}


# ── Modèle de la Forge (`forge/defaut` en base) ──────────────────────────────
# Avant S240, `forge/defaut` était câblé dans le YAML (Mistral small). Il vit désormais en
# base, recréé par le Cœur d'après `forge_modele` (config persistée). Le repli
# `forge/defaut → [gratuit/auto, gratuit/secours]` reste déclaré dans
# `router_settings.fallbacks` du YAML : LiteLLM l'applique au GROUPE `forge/defaut`, qu'il
# vienne du YAML ou de la base (prouvé sur une v1.86.2 locale, cf. message du commit S240 T3).

NOM_FORGE = "forge/defaut"
FORGE_DEFAUT = ("mistral", "mistral-small-latest")
# Frigo court, comme `mistral/*` dans le YAML (S239) : l'heure globale ferait servir la
# Forge par les gratuits pendant 1 h après quelques erreurs passagères.
COOLDOWN_FORGE_S = 120
VEILLE_FORGE_S = int(os.getenv("FORGE_VEILLE_S", "600"))

# `_verrou_forge` : défini plus haut (partagé avec ajouter/retirer).


def params_forge(choix: str) -> dict:
    """`litellm_params` de `forge/defaut` pour un choix ("" = défaut, sinon `perso/*`)."""
    if not choix:
        fournisseur, ident = FORGE_DEFAUT
    else:
        analyse = analyser_nom_perso(choix)
        if analyse is None:
            raise ValeurInvalide("La Forge accepte le modèle par défaut ou un modèle que tu as "
                                 "ajouté (perso/…).")
        fournisseur, ident = analyse
    return {**params_litellm(fournisseur, ident), "cooldown_time": COOLDOWN_FORGE_S}


async def _assurer_forge(choix: str) -> dict:
    """Corps d'`assurer_forge`, à appeler verrou tenu."""
    voulu = params_forge(choix)
    actuels = [d for d in await deploiements() if d["nom"] == NOM_FORGE]
    if any(not d["db"] for d in actuels):
        # Retour arrière (forge/defaut remis dans le YAML) ou déploiement par étapes : le YAML
        # fait foi. Une copie en base le DOUBLERAIT (LiteLLM répartit la charge entre les
        # deux) : on la retire (revue S240, I5). Le YAML lui-même n'est jamais touché d'ici.
        for d in actuels:
            if d["db"] and d["id"]:
                await supprimer(d["id"])
        return {"statut": "yaml", "detail": "forge/defaut est déclaré dans le YAML de la "
                "Gateway : retire-le pour le piloter depuis ⚙ Cerveau."}
    bons = [d for d in actuels if d["model"] == voulu["model"]]
    garde = bons[0] if bons else None
    statut = "ok"
    if garde is None:
        await creer(NOM_FORGE, voulu)
        statut = "repointe" if actuels else "cree"
    for d in actuels:
        if d is not garde and d["id"]:
            await supprimer(d["id"])
    if statut != "ok":
        logger.info("Forge : forge/defaut %s → %s", statut, voulu["model"])
    return {"statut": statut, "model": voulu["model"]}


async def assurer_forge(choix: str | None = None) -> dict:
    """Aligne `forge/defaut` en base sur `choix` (défaut : le choix persisté). Idempotent.

    Ordre : on CRÉE le nouveau avant de retirer l'ancien — LiteLLM accepte deux
    déploiements du même nom (il répartit la charge entre eux), la Forge n'est donc jamais
    sans `forge/defaut`, au pire servie un instant par l'un ou l'autre.

    `forge/defaut` présent dans le YAML : on retire les copies en base et on s'arrête.
    RETOUR ARRIÈRE vers le YAML : remettre le bloc `forge/defaut` dans litellm_config.yaml et
    recréer la Gateway ; au plus tard à la veille suivante (FORGE_VEILLE_S, 10 min), le Cœur
    retire sa copie en base. Pour un effet immédiat : recréer aussi le Cœur, ou appeler
    `/model/delete` sur l'id `forge/defaut` en base (`/model/info`, `db_model: true`)."""
    async with _verrou_forge:
        if choix is None:
            choix = config_assistant.charger().get("forge_modele") or ""
        return await _assurer_forge(choix)


async def definir_forge(choix: str) -> dict:
    """Change le modèle de la Forge : valide, re-pointe `forge/defaut`, le TESTE (sans repli),
    et ne persiste qu'en cas de succès.

    Test en échec (revue S240, I3) : on remet l'ancien pointage et on ne persiste rien — sinon
    la Forge serait servie en silence par les gratuits, et la veille réappliquerait ce choix
    cassé toutes les 10 min. Verrou tenu de bout en bout pour que la veille ne s'intercale
    pas entre le re-pointage, le test et la restauration."""
    choix = (choix or "").strip()
    params_forge(choix)  # valide la forme avant tout appel réseau
    async with _verrou_forge:
        if choix and not any(d["nom"] == choix and d["db"] for d in await deploiements()):
            raise Introuvable(f"« {choix} » n'est pas servi : ajoute-le d'abord.")
        ancien = config_assistant.charger().get("forge_modele") or ""
        r = await _assurer_forge(choix)
        if r["statut"] == "yaml":
            raise Conflit(r["detail"])
        ok, detail = await tester(NOM_FORGE)
        if ok:
            config_assistant.definir_forge_modele(choix)
            return {"ok": True, "choix": choix, "model": r["model"], "detail": detail,
                    "restaure": False}
        try:
            modele_ancien = params_forge(ancien)["model"]
            await _assurer_forge(ancien)
        except (GatewayInjoignable, ValeurInvalide) as e:
            # Réponse HONNÊTE (revue S240, M4) : la Forge pointe encore sur le modèle essayé,
            # qui ne répond pas (donc servie par les gratuits). Le choix persisté reste
            # l'ancien : la veille le réappliquera dès que la Gateway le permettra.
            return {"ok": False, "choix": ancien, "model": r["model"], "restaure": False,
                    "essaye": r["model"],
                    "detail": detail + f" ⚠ Restauration de l'ancien modèle impossible ({e}) : "
                              "la Forge reste pour l'instant sur le modèle essayé ; la veille "
                              "la remettra sur l'ancien automatiquement."}
        return {"ok": False, "choix": ancien, "model": modele_ancien,
                "detail": detail, "restaure": True, "essaye": r["model"]}


def etat_forge() -> dict:
    """Choix de la Forge + état de la clé de SON fournisseur : sans clé, `forge/defaut` échoue
    à chaque appel et la Forge est servie par les gratuits (revue S240, I4)."""
    choix = config_assistant.charger().get("forge_modele") or ""
    analyse = analyser_nom_perso(choix) if choix else None
    fournisseur = analyse[0] if analyse else FORGE_DEFAUT[0]
    cle = next((f for f in config_assistant.cles_fournisseurs_etat() if f["id"] == fournisseur), {})
    return {"choix": choix, "defaut": "/".join(FORGE_DEFAUT), "fournisseur": fournisseur,
            "fournisseur_label": cle.get("label", fournisseur),
            "cle_definie": bool(cle.get("definie"))}


async def veiller_forge(intervalle: int = VEILLE_FORGE_S, reessai: int = 30) -> None:
    """Tâche de fond du Cœur : `forge/defaut` doit toujours exister.

    Au démarrage la Gateway peut ne pas être prête (ou sa base vide après réinstallation) :
    on réessaie toutes les `reessai` s, puis on revérifie toutes les `intervalle` s — une base
    LiteLLM réinitialisée en cours de route retrouve ainsi son `forge/defaut` sans
    redémarrer le Cœur."""
    while True:
        try:
            await assurer_forge()
            attente = intervalle
        except Exception as e:  # noqa: BLE001 — la veille ne doit jamais mourir
            logger.warning("Forge : forge/defaut non vérifié (%s), nouvel essai dans %d s",
                           e, reessai)
            attente = reessai
        await asyncio.sleep(attente)
