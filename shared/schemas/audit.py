"""Contrat de l'audit (S119) — brique `audit` (productrice) → brique `generateur`.

L'audit est une enveloppe (identité + statut + entreprise) portant 4 couches d'analyse
produites par le LLM (territoire, flux, problèmes, priorités). Chaque couche est du JSON
de forme libre (sortie modèle), donc typée `dict | None` ; l'enveloppe, elle, est figée.
`extra="allow"` : on tolère des champs additionnels pour ne pas casser à la moindre
évolution (le contrat fixe le NOYAU, pas un mur).
"""
from typing import Any

from pydantic import BaseModel, ConfigDict

STATUT_EN_COURS = "en_cours"
STATUT_TERMINE = "termine"


class Audit(BaseModel):
    """Audit complet tel qu'exposé par GET /audits/{id} et consommé par le générateur."""

    model_config = ConfigDict(extra="allow")

    id: str
    statut: str = STATUT_EN_COURS
    nom_entreprise: str | None = None
    date_audit: str | None = None
    docs_sources: Any = None
    # Les 4 couches d'analyse (JSON libre produit par le LLM ; absentes si non calculées).
    territoire: dict[str, Any] | None = None
    flux: dict[str, Any] | None = None
    problemes: dict[str, Any] | None = None
    priorites: dict[str, Any] | None = None

    @property
    def est_termine(self) -> bool:
        return self.statut == STATUT_TERMINE
