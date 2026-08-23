"""Logique de croisement cosmique (Sprint A/B), extraite de `main.py` (Sprint C) pour
être appelable SANS HTTP — l'horloge (`horloge_moteur.py`) déclenche des naissances
automatiques par appel de fonction direct, pas par requête HTTP interne."""
from __future__ import annotations

from datetime import date
from random import Random
from typing import Literal, Optional, Union

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

import fusion
import personnages_client
import stockage
import stockage_spatial


class FicheParent(BaseModel):
    """Même forme que FicheHolistique côté personnages — sous-ensemble minimal
    pour ce prototype (pas de systeme_numerologie/langue_sortie ici, YAGNI).

    heure_naissance/latitude/longitude restent optionnels ICI (comme côté
    personnages, repli honnête), mais sont EFFECTIVEMENT nécessaires : sans eux,
    personnages renvoie un theme_complet dégradé (sans dominantes/dix_corps) et
    _exiger_theme_complet() refuse la fiche avec un 422 explicite plutôt que de
    laisser le calcul planter plus loin."""
    model_config = ConfigDict(extra="forbid")

    prenoms: str = ""
    nom: str = ""
    date_naissance: str = ""
    heure_naissance: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset: Optional[float] = None
    sexe: Optional[Literal["F", "M"]] = None  # rôle dans CE croisement (placement, Sprint B) —
                                                # pas un trait de la personne, jamais deviné.


class ReferenceParent(BaseModel):
    """Référence à un enfant déjà stocké (Sprint A), utilisable comme parent d'un
    nouveau croisement — évite de recopier date/heure/lieu de naissance d'un
    enfant déjà généré. `extra="forbid"` sur les deux modèles rend le choix entre
    fiche brute et référence déterministe pour Pydantic (aucun input valide ne
    peut matcher les deux à la fois)."""
    model_config = ConfigDict(extra="forbid")

    id: str
    sexe: Optional[Literal["F", "M"]] = None


ParentInput = Union[ReferenceParent, FicheParent]


class Croisement(BaseModel):
    parent_a: ParentInput
    parent_b: ParentInput
    prenoms_enfant: str = ""
    nom_enfant: str = ""
    latitude_enfant: float       # jamais deviné : requis
    longitude_enfant: float      # jamais deviné : requis
    heure_naissance_enfant: str  # "HH:MM" — jamais deviné : requis (sans elle, personnages
                                  # ne calcule qu'un theme_complet dégradé, sans dix_corps)
    utc_offset_enfant: float     # jamais deviné : requis (un défaut à 0 décale l'ascendant
                                  # de 15-30° pour un lieu européen et fausse maisons/dominantes)
    annee_enfant: Optional[int] = Field(default=None, ge=1, le=9999)
    mutation_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    monde_id: Optional[str] = None  # place l'enfant à sa naissance (Sprint B) — absent = non placé
    sexe_enfant: Optional[Literal["F", "M"]] = None  # trait persistant de l'enfant (Sprint C) —
                                                      # nécessaire à l'horloge pour apparier des couples F/M


def _detail(resp) -> str:
    """Message d'erreur d'une réponse `personnages` non-200 — repli honnête sur le
    texte brut si le corps n'est pas du JSON valide OU n'est pas un objet (ne lève jamais)."""
    try:
        corps = resp.json()
        return corps.get("detail", resp.text) if isinstance(corps, dict) else resp.text
    except ValueError:
        return resp.text


def _propager_ou_502(resp, qui: str) -> None:
    """Propage un 422 de `personnages` tel quel (fiche invalide, faute de l'appelant).
    Tout autre code (401/403/5xx…) signale un problème CÔTÉ world-engine (mauvaise
    clé d'intégration, panne) et devient un 502 — jamais confondu avec un rejet de
    l'appelant, qui verrait sinon SA requête accusée à tort."""
    if resp.status_code == 422:
        raise HTTPException(422, f"{qui} : {_detail(resp)}")
    raise HTTPException(502, f"{qui} : personnages a répondu {resp.status_code} — {_detail(resp)}")


def _exiger_theme_complet(theme: dict, qui: str) -> dict:
    """`personnages` répond 200 avec un theme_complet DÉGRADÉ (sans dominantes ni
    dix_corps) si l'heure ou le lieu de naissance manque ou est malformé — jamais
    une erreur de son côté (repli honnête documenté dans theme_complet.py). On
    refuse honnêtement ICI plutôt que de planter en KeyError plus loin."""
    tc = theme.get("theme_complet") or {}
    manquant = [k for k in ("dominantes", "dix_corps") if k not in tc]
    if manquant:
        raise HTTPException(422, f"{qui} : thème incomplet ({', '.join(manquant)} absent(s)). "
                                  "Fournis une heure de naissance 'HH:MM' valide ET un lieu "
                                  "(latitude/longitude) — jamais devinés.")
    return tc


async def _theme_parent(parent: ParentInput, cle_api_val: str, qui: str) -> dict:
    """Résout le thème d'un parent : soit en rappelant `personnages` (fiche brute),
    soit en relisant un enfant déjà stocké (référence par id) — sans appel réseau
    dans ce second cas."""
    if isinstance(parent, ReferenceParent):
        enfant = stockage.lire(cle_api_val, parent.id)
        if enfant is None:
            raise HTTPException(404, f"{qui} : enfant stocké '{parent.id}' introuvable.")
        return enfant["theme"]
    try:
        # exclude={"sexe"} : rôle dans CE croisement (placement, Sprint B), pas un
        # trait de la fiche envoyée à `personnages` — ne doit jamais franchir la
        # frontière de la brique (voir doc du champ sur FicheParent).
        r = await personnages_client.portrait(parent.model_dump(exclude={"sexe"}))
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if r.status_code != 200:
        _propager_ou_502(r, qui)
    theme = r.json()
    _exiger_theme_complet(theme, qui)
    return theme


def _parent_reference_naissance(parent_a: ParentInput, parent_b: ParentInput) -> ParentInput:
    """Parent de référence pour l'héritage de position à la naissance : celui
    marqué sexe="F" ; à défaut (aucun "F", ou les deux marqués "F"), parent_a."""
    if parent_a.sexe == "F" and parent_b.sexe != "F":
        return parent_a
    if parent_b.sexe == "F" and parent_a.sexe != "F":
        return parent_b
    return parent_a


def _cellule_naissance(monde_id: str, parent_ref: ParentInput, rng: Random) -> int:
    """Cellule de naissance dans `monde_id` (déjà vérifié existant par l'appelant) :
    voisine aléatoire de la cellule du parent de référence s'il y est déjà placé
    DANS CE monde, sinon cellule aléatoire bornée du monde."""
    voisins = None
    if isinstance(parent_ref, ReferenceParent):
        cellule_parent = stockage_spatial.placement_cellule(monde_id, parent_ref.id)
        if cellule_parent is not None:
            voisins = stockage_spatial.voisins_cellule(monde_id, cellule_parent)
    if voisins:
        return rng.choice(voisins)
    nb = stockage_spatial.nb_cellules_monde(monde_id)
    if nb is None:
        # Race rare (TOCTOU) : le monde a été supprimé entre la vérification
        # monde_existe() en tête de route et cet appel (fenêtre des `await` vers
        # personnages). Message lisible plutôt que le TypeError opaque de
        # rng.randrange(None) — capté par le try/except de genome_croiser, il
        # finit dans `avertissement`.
        raise RuntimeError(f"Monde '{monde_id}' supprimé pendant le croisement.")
    return rng.randrange(nb)


async def executer_croisement(body: Croisement, cle_api_val: str) -> dict:
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel, avec
    un récit d'hérédité en post-traitement — coïncidence assumée, pas une vraie
    génétique astrale (voir `fusion.comparer_dix_corps`). Si `monde_id` est fourni,
    l'enfant est aussi placé sur ce monde spatial (Sprint B) — voisin de la cellule
    du parent de référence (sexe="F", sinon parent_a) s'il y est déjà, sinon cellule
    aléatoire bornée. Extrait de la route `/genome/croiser` (Sprint C) pour être
    appelable sans HTTP par l'horloge."""
    if (isinstance(body.parent_a, ReferenceParent) and isinstance(body.parent_b, ReferenceParent)
            and body.parent_a.id == body.parent_b.id):
        raise HTTPException(422, "Un enfant ne peut pas être croisé avec lui-même.")
    if body.monde_id is not None and not stockage_spatial.monde_existe(cle_api_val, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    theme_a = await _theme_parent(body.parent_a, cle_api_val, "Parent A")
    theme_b = await _theme_parent(body.parent_b, cle_api_val, "Parent B")

    description, mutation_survenue = fusion.fusionner_description(
        theme_a, theme_b, body.mutation_rate, Random())

    try:
        rri = await personnages_client.recherche_inverse(description)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if rri.status_code != 200:
        _propager_ou_502(rri, "Recherche inverse")
    signes = rri.json().get("signes") or []
    if not signes:
        raise HTTPException(422, "Impossible de dériver un signe pour l'enfant à partir "
                                  "de cette description fusionnée.")

    annee = body.annee_enfant or date.today().year
    date_enfant = fusion.date_pour_signe(signes[0]["signe"], annee)

    fiche_enfant = {
        "prenoms": body.prenoms_enfant, "nom": body.nom_enfant,
        "date_naissance": date_enfant, "heure_naissance": body.heure_naissance_enfant,
        "latitude": body.latitude_enfant, "longitude": body.longitude_enfant,
        "utc_offset": body.utc_offset_enfant,
    }
    try:
        re_ = await personnages_client.portrait(fiche_enfant)
    except personnages_client.PersonnagesIndisponible as e:
        raise HTTPException(502, f"Brique personnages injoignable : {e}")
    if re_.status_code != 200:
        _propager_ou_502(re_, "Enfant")
    theme_enfant = re_.json()
    _exiger_theme_complet(theme_enfant, "Enfant")

    heredite = fusion.comparer_dix_corps(
        theme_enfant["theme_complet"]["dix_corps"],
        theme_a["theme_complet"]["dix_corps"],
        theme_b["theme_complet"]["dix_corps"])

    parent_a_id = body.parent_a.id if isinstance(body.parent_a, ReferenceParent) else None
    parent_b_id = body.parent_b.id if isinstance(body.parent_b, ReferenceParent) else None
    try:
        enfant_id = stockage.creer(cle_api_val, body.prenoms_enfant, body.nom_enfant,
                                    parent_a_id, parent_b_id, theme_enfant,
                                    description, heredite, mutation_survenue, body.sexe_enfant)
        avertissement = None
    except Exception as e:
        enfant_id = None
        avertissement = f"Enfant calculé mais non persisté : {e}"

    cellule_id = None
    if body.monde_id is not None and enfant_id is not None:
        try:
            parent_ref = _parent_reference_naissance(body.parent_a, body.parent_b)
            cellule_id = _cellule_naissance(body.monde_id, parent_ref, Random())
            stockage_spatial.placer(body.monde_id, enfant_id, cellule_id)
        except Exception as e:
            cellule_id = None
            avertissement = f"Enfant persisté mais non placé : {e}"

    return {"parentA": theme_a, "parentB": theme_b, "description_genome": description,
            "enfant": theme_enfant, "heredite": heredite, "mutation_survenue": mutation_survenue,
            "enfant_id": enfant_id, "cellule_id": cellule_id, "avertissement": avertissement}
