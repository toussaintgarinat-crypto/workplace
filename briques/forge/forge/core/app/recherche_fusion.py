"""Fonctions pures de la recherche documentaire Forge (S241) : références exactes, RRF, ordre.

Copie adaptée de la Mémoire (S238, briques/memoire/memory/backend/app/services/recherche_fusion.py) :
les briques ne partagent pas de code. Différence : un résultat est identifié par une clé
(source, id), documents et articles vivant dans deux tables.

Les scores lexicaux (ts_rank_cd) et vectoriels (cosinus) ne sont pas comparables : on ne les
additionne jamais, on fusionne les RANGS (Reciprocal Rank Fusion).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

K_RRF = 60
LONGUEUR_REFERENCE_MAX = 100
REFERENCES_MAX = 10

Cle = tuple[str, UUID]

_GUILLEMETS = re.compile(r'"([^"]+)"|«\s*([^»]+?)\s*»|"([^"]+)"')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»""…"


def _est_reference(jeton: str) -> bool:
    return (
        len(jeton) >= 2
        and any(c.isalnum() for c in jeton)
        and (any(c.isdigit() for c in jeton) or any(c in _CARACTERES_REFERENCE for c in jeton))
    )


def extraire_references(requete: str) -> list[str]:
    """Expressions entre guillemets, puis jetons qui ressemblent à un code (chiffre ou
    `-_./@#`). Dédoublonnées sans tenir compte de la casse, dans l'ordre d'apparition."""
    candidates = []
    for m in _GUILLEMETS.finditer(requete):
        expression = " ".join(next(g for g in m.groups() if g).split())
        if expression and len(expression) <= LONGUEUR_REFERENCE_MAX:
            candidates.append(expression)
    for jeton in _GUILLEMETS.sub(" ", requete).split():
        jeton = jeton.strip(_BORDS)
        if _est_reference(jeton) and len(jeton) <= LONGUEUR_REFERENCE_MAX:
            candidates.append(jeton)
    vues, references = set(), []
    for c in candidates:
        if c.casefold() not in vues:
            vues.add(c.casefold())
            references.append(c)
    return references[:REFERENCES_MAX]


def motif_reference(reference: str) -> str:
    """Motif ARE PostgreSQL trouvant `reference` comme mot entier. `reference` doit être DÉJÀ
    normalisée en SQL (forge_unaccent(lower(...))) : normaliser après l'échappement pourrait
    produire des métacaractères (unaccent développe ⁇ en ??). Seuls les métacaractères ARE
    ASCII sont échappés ; les espaces d'une expression acceptent tout blanc."""
    morceaux = [re.sub(r"([\\^$.|?*+()\[\]{}])", r"\\\1", m) for m in reference.split()]
    return "(^|[^[:alnum:]])" + "[[:space:]]+".join(morceaux) + "($|[^[:alnum:]])"


def fusion_rrf(classements: list[list[Cle]], k: int = K_RRF) -> dict[Cle, float]:
    scores: dict[Cle, float] = {}
    for classement in classements:
        for rang, cle in enumerate(classement, start=1):
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (k + rang)
    return scores


@dataclass(frozen=True)
class CorrespondanceExacte:
    references_trouvees: int
    dans_titre: bool


@dataclass(frozen=True)
class Classe:
    cle: Cle
    score: float
    correspondance: str  # exacte | lexicale | vectorielle | les_deux


def ordonner(
    exacts: dict[Cle, CorrespondanceExacte],
    lexical: list[Cle],
    vectoriel: list[Cle],
    limite: int,
) -> list[Classe]:
    """Références exactes d'abord (plus de références trouvées, puis titre avant contenu, puis
    rang de fusion), ensuite le reste par score RRF décroissant.

    Un score de fusion vaut au plus 2/(K_RRF+1) < 0,04 : le palier exact
    (1 + nombre de références + 0,5 si dans le titre) reste toujours au-dessus."""
    if limite < 1:
        return []
    fusion = fusion_rrf([lexical, vectoriel])
    ens_lex, ens_vec = set(lexical), set(vectoriel)

    def correspondance(c: Cle) -> str:
        if c in exacts:
            return "exacte"
        if c in ens_lex and c in ens_vec:
            return "les_deux"
        return "lexicale" if c in ens_lex else "vectorielle"

    scores = {}
    for c in set(fusion) | set(exacts):
        s = fusion.get(c, 0.0)
        if c in exacts:
            s += 1.0 + exacts[c].references_trouvees + (0.5 if exacts[c].dans_titre else 0.0)
        scores[c] = s
    ordre = sorted(scores, key=lambda c: (-scores[c], c[0], str(c[1])))[:limite]
    # Rangs croisés → scores RRF égaux : un epsilon de position rend la suite strictement
    # décroissante sans changer l'ordre.
    n = len(ordre)
    return [Classe(c, scores[c] + (n - pos) * 1e-9, correspondance(c)) for pos, c in enumerate(ordre)]
