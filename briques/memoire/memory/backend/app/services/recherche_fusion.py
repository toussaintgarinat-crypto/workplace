"""Fonctions pures de la recherche Mémoire (S238) : références exactes, fusion RRF, ordre.

Aucun accès base ici. Les scores lexicaux (ts_rank_cd) et vectoriels (cosinus) ne sont pas
comparables : on ne les additionne jamais, on fusionne les RANGS (Reciprocal Rank Fusion).
"""
import re
from dataclasses import dataclass
from uuid import UUID

K_RRF = 60
LONGUEUR_REFERENCE_MAX = 100
REFERENCES_MAX = 10

_GUILLEMETS = re.compile(r'"([^"]+)"|«\s*([^»]+?)\s*»|“([^”]+)”')
_CARACTERES_REFERENCE = set("-_./@#")
_BORDS = ".,;:!?()[]{}'\"«»“”…"


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
    """Motif ARE PostgreSQL trouvant `reference` comme mot entier. `reference` doit être
    DÉJÀ normalisée (memoire_unaccent(lower(...)) côté SQL, voir correspondances_exactes) :
    le motif est comparé tel quel, sans retraitement. Normaliser après avoir construit le
    motif casserait l'échappement, car unaccent développe certains symboles en
    métacaractères (⁇ devient ??, … devient ..., © devient (C)) ou en lettres (™ devient TM,
    et `\\™` deviendrait `\\TM`, échappement invalide). Seuls les métacaractères ARE ASCII
    (\\ ^ $ . | ? * + ( ) [ ] { }) sont échappés ; tout autre caractère est littéral en ARE
    hors crochets. Les espaces d'une expression acceptent tout blanc."""
    morceaux = [re.sub(r"([\\^$.|?*+()\[\]{}])", r"\\\1", m) for m in reference.split()]
    return "(^|[^[:alnum:]])" + "[[:space:]]+".join(morceaux) + "($|[^[:alnum:]])"


def fusion_rrf(classements: list[list[UUID]], k: int = K_RRF) -> dict[UUID, float]:
    scores: dict[UUID, float] = {}
    for classement in classements:
        for rang, ident in enumerate(classement, start=1):
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + rang)
    return scores


@dataclass(frozen=True)
class CorrespondanceExacte:
    references_trouvees: int
    dans_titre: bool


@dataclass(frozen=True)
class Classe:
    id: UUID
    score: float
    correspondance: str  # exacte | lexicale | vectorielle | les_deux


def ordonner(
    exacts: dict[UUID, CorrespondanceExacte],
    lexical: list[UUID],
    vectoriel: list[UUID],
    limite: int,
) -> list[Classe]:
    """Références exactes d'abord (plus de références trouvées, puis titre avant contenu,
    puis rang de fusion), ensuite le reste par score RRF décroissant.

    Un score de fusion vaut au plus 2/(K_RRF+1) < 0,04 : le palier exact
    (1 + nombre de références + 0,5 si dans le titre) reste toujours au-dessus, et l'ordre
    par score décroissant reproduit exactement l'ordre voulu."""
    if limite < 1:
        return []
    fusion = fusion_rrf([lexical, vectoriel])
    ens_lex, ens_vec = set(lexical), set(vectoriel)

    def correspondance(i: UUID) -> str:
        if i in exacts:
            return "exacte"
        if i in ens_lex and i in ens_vec:
            return "les_deux"
        return "lexicale" if i in ens_lex else "vectorielle"

    scores = {}
    for i in set(fusion) | set(exacts):
        s = fusion.get(i, 0.0)
        if i in exacts:
            s += 1.0 + exacts[i].references_trouvees + (0.5 if exacts[i].dans_titre else 0.0)
        scores[i] = s
    ordre = sorted(scores, key=lambda i: (-scores[i], str(i)))[:limite]
    # Deux souvenirs à rangs croisés (1er ici, 2e là, et inversement) ont le même score RRF :
    # un epsilon de position rend les scores strictement décroissants sans changer l'ordre.
    n = len(ordre)
    return [Classe(i, scores[i] + (n - pos) * 1e-9, correspondance(i)) for pos, i in enumerate(ordre)]
