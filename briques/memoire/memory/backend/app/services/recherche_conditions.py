"""Clause WHERE commune à TOUTES les branches de recherche (alias de table `n`).

Seul endroit où se décide quels souvenirs sont visibles : l'espace (le contrôle d'accès à
l'espace est fait en amont par `check_space_access`), le statut et les filtres. Aucune
branche ne construit sa propre clause : aucune ne peut oublier l'espace.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class Filtres:
    space_id: UUID
    type: Optional[str] = None
    etape: Optional[str] = None
    tier: Optional[str] = None


def conditions_sql(f: Filtres) -> tuple[str, dict]:
    conditions = ["n.space_id = :space_id", "n.status IN ('active', 'archived')"]
    params: dict = {"space_id": f.space_id}
    if f.type:
        conditions.append("n.type = :filtre_type")
        params["filtre_type"] = f.type
    if f.etape:
        conditions.append("n.ipcra_stage = :filtre_etape")
        params["filtre_etape"] = f.etape
    if f.tier:
        conditions.append("n.storage_tier = :filtre_tier")
        params["filtre_tier"] = f.tier
    return " AND ".join(conditions), params
