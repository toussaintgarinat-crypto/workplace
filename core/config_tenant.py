"""Couches de patch déclaratif pour la config assistant (3e chantier veille dsh/Cordis).

Résout `config_assistant.charger()` (modèle/persona/voix/langue…) en 3 couches de
priorité croissante : global (fichier local, inchangé) → organisation → utilisateur
(ces deux dernières stockées dans la brique `données`, scopées par `X-Org-ID`). Fusion
façon JSON Merge Patch (RFC 7386) : toute valeur non-dict — listes incluses — remplace
entièrement celle de la couche du dessous ; les dicts imbriqués sont fusionnés
récursivement (aucun champ du schéma actuel n'en a, mais le mécanisme reste correct
si un futur champ en ajoute un).

Cf. docs/superpowers/specs/2026-08-22-config-tenant-couches-patch-design.md.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# Mêmes conventions que core/muscle.py : env var d'override, pas de dépendance au
# registre de briques (brique connue à l'avance, comme calcul/5990).
DONNEES_URL = os.getenv("DONNEES_URL", "http://host.docker.internal:5500").rstrip("/")
_TIMEOUT = float(os.getenv("CONFIG_TENANT_TIMEOUT", "5"))
_TTL_S = float(os.getenv("CONFIG_TENANT_CACHE_TTL", "90"))

APP_ID = "_config_assistant"
ENTITE_ORGANISATION = "_organisation"
ORG_DEFAUT = "defaut"

# Cache process : (niveau, org_id, entite_id) -> (timestamp_pose, patch)
_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}


def _org_eff(org_id: str | None) -> str:
    return org_id or ORG_DEFAUT


def _fusion(base: dict, patch: dict) -> dict:
    """Fusion façon JSON Merge Patch (RFC 7386)."""
    resultat = dict(base)
    for cle, val in patch.items():
        if isinstance(val, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusion(resultat[cle], val)
        else:
            resultat[cle] = val
    return resultat


def _url(entite_id: str) -> str:
    return f"{DONNEES_URL}/apps/{APP_ID}/entites/{entite_id}/enregistrements"


def _sans_metadonnees(enregistrement: dict) -> dict:
    return {k: v for k, v in enregistrement.items() if not str(k).startswith("_")}


async def _lire_couche(niveau: str, org_id: str, entite_id: str,
                       client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut d'une couche, {} si absente. Sert le cache dans le TTL sans appel
    réseau. Hors TTL, tente une lecture fraîche ; si la brique données est injoignable,
    sert le cache même expiré (mieux qu'un repli silencieux vers le global seul). Sans
    aucun cache et brique down, renvoie {} — la résolution continue avec les couches
    disponibles. Ne lève jamais : `except` ciblé sur les erreurs réseau/parsing."""
    cle_cache = (niveau, org_id, entite_id)
    pose = _cache.get(cle_cache)
    if pose and (time.monotonic() - pose[0]) < _TTL_S:
        return pose[1]

    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.get(_url(entite_id), headers={"X-Org-ID": org_id})
        r.raise_for_status()
        enregistrements = r.json()
        patch = _sans_metadonnees(enregistrements[-1]) if enregistrements else {}
        _cache[cle_cache] = (time.monotonic(), patch)
        return patch
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("brique données injoignable (lecture %s/%s/%s) : %s",
                       niveau, org_id, entite_id, e)
        return pose[1] if pose else {}
    finally:
        if propre:
            await client.aclose()


async def lire_couche_organisation(org_id: str | None,
                                   client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche organisation (pas le résolu)."""
    return await _lire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION, client)


async def lire_couche_utilisateur(org_id: str | None, utilisateur: str,
                                  client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche utilisateur (pas le résolu)."""
    return await _lire_couche("utilisateur", _org_eff(org_id), utilisateur, client)


async def resoudre(org_id: str | None, utilisateur: str,
                   client: httpx.AsyncClient | None = None) -> dict:
    """Config résolue : global < organisation < utilisateur (JSON Merge Patch)."""
    return (await resoudre_avec_provenance(org_id, utilisateur, client))["resolu"]


async def resoudre_avec_provenance(org_id: str | None, utilisateur: str,
                                   client: httpx.AsyncClient | None = None) -> dict:
    """Résolu + provenance : pour chaque clé effectivement patchée par une couche,
    quelle couche a eu le dernier mot ('organisation'|'utilisateur'). Une clé absente
    de `provenance` vient de la couche globale (comportement par défaut) — cohérent
    avec l'invariant « visible du modèle = traçable » (journal_modele)."""
    import config_assistant  # import tardif : évite tout cycle au chargement
    base = config_assistant.charger()
    patch_org = await lire_couche_organisation(org_id, client)
    patch_user = await lire_couche_utilisateur(org_id, utilisateur, client) if utilisateur else {}
    resolu = _fusion(_fusion(base, patch_org), patch_user)
    provenance = {cle: "organisation" for cle in patch_org}
    provenance.update({cle: "utilisateur" for cle in patch_user})
    return {"resolu": resolu, "provenance": provenance}


def _cles_connues() -> frozenset:
    import config_assistant  # import tardif : évite tout cycle au chargement
    return frozenset(config_assistant.charger().keys())


def valider_patch(patch: dict) -> None:
    """Lève ValueError si le patch contient une clé hors du schéma connu de
    config_assistant.charger() — jamais de clé inconnue écrite silencieusement."""
    inconnues = set(patch) - _cles_connues()
    if inconnues:
        raise ValueError(f"clé(s) inconnue(s) : {', '.join(sorted(inconnues))}")


async def _ecrire_couche(niveau: str, org_id: str, entite_id: str, patch: dict,
                         client: httpx.AsyncClient | None = None) -> dict:
    """Fusionne `patch` sur la couche existante et la persiste (upsert : PUT si un
    enregistrement existe déjà pour (app_id, entite_id), POST sinon). Jamais
    silencieuse : une erreur réseau vers données remonte à l'appelant (pas de faux
    succès, pas de patch perdu sans le dire)."""
    valider_patch(patch)
    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        entetes = {"X-Org-ID": org_id}
        r = await client.get(_url(entite_id), headers=entetes)
        r.raise_for_status()
        existants = r.json()
        if existants:
            actuel = _sans_metadonnees(existants[-1])
            nouveau = _fusion(actuel, patch)
            r = await client.put(f"{_url(entite_id)}/{existants[-1]['_id']}",
                                 json=nouveau, headers=entetes)
        else:
            nouveau = dict(patch)
            r = await client.post(_url(entite_id), json=nouveau, headers=entetes)
        r.raise_for_status()
        resultat = _sans_metadonnees(r.json())
        _cache[(niveau, org_id, entite_id)] = (time.monotonic(), resultat)
        return resultat
    finally:
        if propre:
            await client.aclose()


async def ecrire_couche_organisation(org_id: str | None, patch: dict,
                                     client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche organisation. Lève ValueError (clé inconnue) ou
    httpx.HTTPError (brique données injoignable)."""
    return await _ecrire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION,
                                patch, client)


async def ecrire_couche_utilisateur(org_id: str | None, utilisateur: str, patch: dict,
                                    client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche utilisateur. Lève ValueError (clé inconnue) ou
    httpx.HTTPError (brique données injoignable)."""
    return await _ecrire_couche("utilisateur", _org_eff(org_id), utilisateur, patch, client)
