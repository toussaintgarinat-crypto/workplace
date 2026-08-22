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

_cache = {}


def _fusion(base: dict, patch: dict) -> dict:
    """Fusion façon JSON Merge Patch (RFC 7386)."""
    resultat = dict(base)
    for cle, val in patch.items():
        if isinstance(val, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusion(resultat[cle], val)
        else:
            resultat[cle] = val
    return resultat
