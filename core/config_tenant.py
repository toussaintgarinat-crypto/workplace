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
import asyncio
import collections
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
_TTL_NEGATIF_S = float(os.getenv("CONFIG_TENANT_CACHE_TTL_NEGATIF", "10"))

APP_ID = "_config_assistant"
ENTITE_ORGANISATION = "_organisation"
ORG_DEFAUT = "defaut"

# Cache process : (niveau, org_id, entite_id) -> (timestamp_pose, patch)
# Borné (LRU) : sans plafond, chaque couple (org_id, utilisateur) vu laisserait une
# entrée à vie — tenable en mono-org, pas dans le multi-org que ce chantier prépare
# (trouvé en revue finale de branche 2026-08-22).
_CACHE_MAX = int(os.getenv("CONFIG_TENANT_CACHE_MAX", "5000"))
_cache: "collections.OrderedDict[tuple[str, str, str], tuple[float, dict]]" = collections.OrderedDict()


def _cache_get(cle: tuple[str, str, str]):
    pose = _cache.get(cle)
    if pose is not None:
        _cache.move_to_end(cle)
    return pose


def _cache_set(cle: tuple[str, str, str], valeur: tuple[float, dict]) -> None:
    _cache[cle] = valeur
    _cache.move_to_end(cle)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


class ValeurInvalide(ValueError):
    """Patch ou identifiant rejeté (clé inconnue, valeur mal typée, entité réservée)."""


# `org_id` vient d'une ContextVar posée depuis l'en-tête client X-Org-ID (pas de JWT
# aujourd'hui — frontière de confiance partagée avec d'autres appels S2S existants,
# hors périmètre de ce chantier, cf. revue finale de branche 2026-08-22).
def _org_eff(org_id: str | None) -> str:
    return org_id or ORG_DEFAUT


def _utilisateur_valide(utilisateur: str) -> bool:
    """Un identifiant utilisateur commençant par « _ » collisionnerait avec les
    entités réservées (ex. ENTITE_ORGANISATION = "_organisation") dans le même
    magasin (app_id, entite_id) de la brique données."""
    return not utilisateur.startswith("_")


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
    disponibles. Ne lève jamais : `except` ciblé sur les erreurs réseau/parsing, PLUS une
    garde de forme sur la réponse (un 200 malformé ne lève pas non plus). Une lecture en
    échec pose un cache négatif de _TTL_NEGATIF_S : une brique données durablement en
    panne n'est retentée qu'une fois par fenêtre, pas à chaque tour de chat."""
    cle_cache = (niveau, org_id, entite_id)
    pose = _cache_get(cle_cache)
    if pose and (time.monotonic() - pose[0]) < _TTL_S:
        return pose[1]

    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await client.get(_url(entite_id), headers={"X-Org-ID": org_id})
        r.raise_for_status()
        enregistrements = r.json()
        # Garde de FORME (pas seulement de vérité) : une réponse 200 malformée
        # (dict au lieu d'une liste, liste de scalaires…) levait KeyError/AttributeError
        # — non rattrapé par l'`except` ci-dessous, donc échappait et tuait le tour de
        # chat que cette fonction existe justement pour protéger (revue finale
        # de branche 2026-08-22).
        if (isinstance(enregistrements, list) and enregistrements
                and isinstance(enregistrements[-1], dict)):
            patch = _sans_metadonnees(enregistrements[-1])
        else:
            patch = {}
        _cache_set(cle_cache, (time.monotonic(), patch))
        return patch
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("brique données injoignable (lecture %s/%s/%s) : %s",
                       niveau, org_id, entite_id, e)
        repli = pose[1] if pose else {}
        # Cache négatif court : une brique données en panne/lente ne doit payer le
        # coût réseau qu'une fois par fenêtre, pas à chaque tour de chat. La formule
        # place l'entrée juste avant expiration normale, donc « fraîche » seulement
        # pour _TTL_NEGATIF_S secondes à partir de maintenant.
        _cache_set(cle_cache, (time.monotonic() - _TTL_S + _TTL_NEGATIF_S, repli))
        return repli
    finally:
        if propre:
            await client.aclose()


async def _rien() -> dict:
    return {}


async def lire_couche_organisation(org_id: str | None,
                                   client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche organisation (pas le résolu)."""
    return await _lire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION, client)


async def lire_couche_utilisateur(org_id: str | None, utilisateur: str,
                                  client: httpx.AsyncClient | None = None) -> dict:
    """Patch brut de la couche utilisateur (pas le résolu)."""
    if not _utilisateur_valide(utilisateur):
        return {}
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
    # Les deux couches sont indépendantes : en série, le chemin de chat payait deux
    # fois la latence réseau pour rien (revue finale de branche 2026-08-22).
    patch_org, patch_user = await asyncio.gather(
        lire_couche_organisation(org_id, client),
        lire_couche_utilisateur(org_id, utilisateur, client) if utilisateur else _rien(),
    )
    resolu = _fusion(_fusion(base, patch_org), patch_user)
    provenance = {cle: "organisation" for cle in patch_org}
    provenance.update({cle: "utilisateur" for cle in patch_user})
    return {"resolu": resolu, "provenance": provenance}


def _cles_connues() -> frozenset:
    import config_assistant  # import tardif : évite tout cycle au chargement
    return frozenset(config_assistant.charger().keys())


_TYPES_SIMPLES: dict[str, type | tuple[type, ...]] = {
    "model": str, "voix_provider": str, "unmute_url": str, "wakeword_url": str,
    "persona": str, "langue": str, "modele_econome": str, "modele_resume": str,
    "shadow_candidat": str, "repli_payant": str, "repli_souverain": str,
    "voix_silence_ms": int, "cascade_free_n": int,
    "shadow_taux": (int, float),
    "routage_actif": bool, "resume_actif": bool, "shadow_actif": bool,
    "cascade_auto": bool, "muscle_actif": bool, "repli_souverain_avant_payant": bool,
}
# Deux clés du schéma ont une forme spéciale, hors table simple : `fallback_models`
# (liste de chaînes) et `voix_fin_mode` (énumération 'appui'|'silence').


def valider_patch(patch: dict) -> None:
    """Lève ValeurInvalide si le patch contient une clé hors du schéma connu de
    config_assistant.charger(), ou une valeur d'un type incompatible avec ce que
    charger() attend pour cette clé.

    Sans ce contrôle de type (pas seulement de nom), un patch mal typé (ex.
    cascade_free_n: "trois") était accepté (200) puis faisait planter
    chaine_modeles() à CHAQUE tour de chat du tenant, sans recours — trouvé en
    revue finale de branche (2026-08-22), Critical #1."""
    inconnues = set(patch) - _cles_connues()
    if inconnues:
        raise ValeurInvalide(f"clé(s) inconnue(s) : {', '.join(sorted(inconnues))}")
    erreurs = []
    for cle, val in patch.items():
        if cle == "fallback_models":
            if not (isinstance(val, list) and all(isinstance(v, str) for v in val)):
                erreurs.append(f"{cle} doit être une liste de chaînes")
        elif cle == "voix_fin_mode":
            if val not in ("appui", "silence"):
                erreurs.append(f"{cle} doit être 'appui' ou 'silence'")
        elif cle in _TYPES_SIMPLES:
            attendu = _TYPES_SIMPLES[cle]
            if attendu is bool:
                if not isinstance(val, bool):
                    erreurs.append(f"{cle} doit être un booléen")
            elif attendu is str:
                if not isinstance(val, str):
                    erreurs.append(f"{cle} doit être une chaîne")
            else:  # int, ou (int, float)
                if isinstance(val, bool) or not isinstance(val, attendu):
                    erreurs.append(f"{cle} doit être un nombre")
    if erreurs:
        raise ValeurInvalide("; ".join(erreurs))


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
        # Même garde de forme que _lire_couche : une réponse 200 malformée ne doit pas
        # produire un KeyError/AttributeError opaque (revue finale de branche 2026-08-22).
        if isinstance(existants, list) and existants and isinstance(existants[-1], dict):
            actuel = _sans_metadonnees(existants[-1])
            nouveau = _fusion(actuel, patch)
            r = await client.put(f"{_url(entite_id)}/{existants[-1]['_id']}",
                                 json=nouveau, headers=entetes)
        else:
            nouveau = dict(patch)
            r = await client.post(_url(entite_id), json=nouveau, headers=entetes)
        r.raise_for_status()
        resultat = _sans_metadonnees(r.json())
        _cache_set((niveau, org_id, entite_id), (time.monotonic(), resultat))
        return resultat
    finally:
        if propre:
            await client.aclose()


async def ecrire_couche_organisation(org_id: str | None, patch: dict,
                                     client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche organisation. Lève ValeurInvalide (clé inconnue ou
    valeur mal typée) ou httpx.HTTPError (brique données injoignable)."""
    return await _ecrire_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION,
                                patch, client)


async def ecrire_couche_utilisateur(org_id: str | None, utilisateur: str, patch: dict,
                                    client: httpx.AsyncClient | None = None) -> dict:
    """Patch (partiel) la couche utilisateur. Lève ValeurInvalide (clé inconnue, valeur
    mal typée, identifiant réservé) ou httpx.HTTPError (brique données injoignable)."""
    if not _utilisateur_valide(utilisateur):
        raise ValeurInvalide("identifiant utilisateur invalide (ne doit pas commencer par '_')")
    return await _ecrire_couche("utilisateur", _org_eff(org_id), utilisateur, patch, client)


async def _supprimer_couche(niveau: str, org_id: str, entite_id: str,
                            client: httpx.AsyncClient | None = None) -> None:
    """Supprime la couche si elle existe (no-op sinon) — seul recours pour retirer un
    patch (y compris un patch invalide persisté avant le correctif de Fix 1). Jamais
    silencieuse sur panne réseau, comme _ecrire_couche."""
    propre = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        entetes = {"X-Org-ID": org_id}
        r = await client.get(_url(entite_id), headers=entetes)
        r.raise_for_status()
        existants = r.json()
        if (isinstance(existants, list) and existants
                and isinstance(existants[-1], dict) and "_id" in existants[-1]):
            r = await client.delete(f"{_url(entite_id)}/{existants[-1]['_id']}", headers=entetes)
            r.raise_for_status()
        _cache.pop((niveau, org_id, entite_id), None)
    finally:
        if propre:
            await client.aclose()


async def supprimer_couche_organisation(org_id: str | None,
                                        client: httpx.AsyncClient | None = None) -> None:
    await _supprimer_couche("organisation", _org_eff(org_id), ENTITE_ORGANISATION, client)


async def supprimer_couche_utilisateur(org_id: str | None, utilisateur: str,
                                       client: httpx.AsyncClient | None = None) -> None:
    if not _utilisateur_valide(utilisateur):
        raise ValeurInvalide("identifiant utilisateur invalide (ne doit pas commencer par '_')")
    await _supprimer_couche("utilisateur", _org_eff(org_id), utilisateur, client)
