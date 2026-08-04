"""Point de contrôle avant éviction d'une session — relai propre entre appareils.

Stub aujourd'hui : journalise seulement. Point d'extension volontairement isolé du reste
du chantier de session (`session_registre.py`, `core/auth.py`) pour que ce dernier reste
testable sans dépendre du chantier de sauvegarde continue.

Quand `docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md` sera livré, ce module
sera le seul à modifier pour déclencher un vrai cliché de réplication immédiat (appel HTTP
vers un futur point de contrôle Litestream, ou `wal-g wal-push` forcé) au lieu d'attendre le
cycle normal de réplication (quelques secondes) — aucun appelant de ce module n'aura à
changer.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def declencher_checkpoint(sub: str) -> None:
    """Point de contrôle avant de considérer une ancienne session comme close.

    Stub : journalise l'intention. Ne lève jamais — un échec de checkpoint ne doit pas
    empêcher le relai vers le nouvel appareil (la réplication continue, une fois branchée,
    tournera de toute façon dans les quelques secondes suivantes ; ce point de contrôle
    n'est qu'une garantie SUPPLÉMENTAIRE, pas la seule ligne de défense)."""
    logger.info("Relai de session pour %s : point de contrôle déclenché", sub)
