"""Brique « world-engine » — croisement de 2 profils cosmiques (génome cosmique).

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de `personnages` (port 5900) en HTTP pour tout
calcul astral — ne duplique jamais le moteur.
"""
import os
from datetime import date
from random import Random
from typing import Literal, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import fusion
import personnages_client
import spatial
import stockage
import stockage_spatial

app = FastAPI(title="World Engine — Génome Cosmique", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}
if os.getenv("WORLD_ENGINE_KEY", "").strip():
    API_KEYS.add(os.getenv("WORLD_ENGINE_KEY").strip())


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    """Valide la clé API (header X-API-Key ou Authorization: Bearer).

    API_KEYS vide (défaut dev) = mode ouvert. Même motif que `briques/personnages`."""
    if not API_KEYS:
        return "public"
    cle = x_api_key
    if not cle and authorization and authorization.startswith("Bearer "):
        cle = authorization[7:]
    if cle not in API_KEYS:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return cle


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "brique": "world-engine"}


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


class CreerMonde(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nb_cellules: int = Field(ge=10, le=2000)
    seed: Optional[int] = None


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
        r = await personnages_client.portrait(parent.model_dump())
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
    return rng.randrange(stockage_spatial.nb_cellules_monde(monde_id))


@app.post("/genome/croiser", tags=["genome"])
async def genome_croiser(body: Croisement, _cle: str = Depends(cle_api)):
    """Croise 2 profils cosmiques (via `personnages`, ou un enfant déjà stocké
    référencé par id) pour produire un enfant au thème astronomiquement réel, avec
    un récit d'hérédité en post-traitement — coïncidence assumée, pas une vraie
    génétique astrale (voir `fusion.comparer_dix_corps`). Si `monde_id` est fourni,
    l'enfant est aussi placé sur ce monde spatial (Sprint B) — voisin de la cellule
    du parent de référence (sexe="F", sinon parent_a) s'il y est déjà, sinon cellule
    aléatoire bornée."""
    if (isinstance(body.parent_a, ReferenceParent) and isinstance(body.parent_b, ReferenceParent)
            and body.parent_a.id == body.parent_b.id):
        raise HTTPException(422, "Un enfant ne peut pas être croisé avec lui-même.")
    if body.monde_id is not None and not stockage_spatial.monde_existe(_cle, body.monde_id):
        raise HTTPException(404, f"Monde '{body.monde_id}' introuvable.")
    theme_a = await _theme_parent(body.parent_a, _cle, "Parent A")
    theme_b = await _theme_parent(body.parent_b, _cle, "Parent B")

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
        enfant_id = stockage.creer(_cle, body.prenoms_enfant, body.nom_enfant,
                                    parent_a_id, parent_b_id, theme_enfant,
                                    description, heredite, mutation_survenue)
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


@app.get("/genome/enfants", tags=["genome"])
def genome_enfants_lister(_cle: str = Depends(cle_api)):
    return stockage.lister(_cle)


@app.get("/genome/enfants/{eid}", tags=["genome"])
def genome_enfant_lire(eid: str, _cle: str = Depends(cle_api)):
    enfant = stockage.lire(_cle, eid)
    if enfant is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return enfant


@app.delete("/genome/enfants/{eid}", status_code=204, tags=["genome"])
def genome_enfant_supprimer(eid: str, _cle: str = Depends(cle_api)):
    if not stockage.supprimer(_cle, eid):
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")


def _noeud_arbre(cle_api_val: str, eid: str, vus: set[str] | None = None) -> dict | None:
    """Reconstruit récursivement la lignée d'un enfant stocké. S'arrête dès qu'un
    parent est absent (fiche brute d'origine, ou enfant stocké supprimé entre-temps
    — les deux cas sont indistinguables et traités pareil : branche `null`).

    La chaîne de parenté est un DAG par construction (ids uuid4, arêtes remontant
    toujours vers le passé — donc acyclique), PAS un arbre : un même ancêtre peut
    être atteignable par plusieurs chemins (ex. deux enfants croisés qui partagent
    un grand-parent, ou même parent_a == parent_b). `vus` mémoïse les ids déjà
    développés dans CE parcours pour éviter une ré-expansion exponentielle du
    même sous-arbre et pour ne jamais présenter un même ancêtre comme s'il
    s'agissait de personnes distinctes. Un ancêtre déjà développé ailleurs revient
    en stub `{"id":..., "prenoms":..., "nom":..., "deja_present": True}` — jamais
    en `None` : les deux ont un sens différent pour l'appelant (`None` = pas
    d'ancêtre stocké au-delà de ce point, stub = ancêtre stocké mais déjà montré
    ailleurs dans cet arbre)."""
    vus = set() if vus is None else vus
    enfant = stockage.lire(cle_api_val, eid)
    if enfant is None:
        return None
    if eid in vus:
        return {"id": enfant["id"], "prenoms": enfant["prenoms"], "nom": enfant["nom"],
                "deja_present": True}
    vus.add(eid)
    return {
        "id": enfant["id"], "prenoms": enfant["prenoms"], "nom": enfant["nom"],
        "parent_a": _noeud_arbre(cle_api_val, enfant["parent_a_id"], vus) if enfant["parent_a_id"] else None,
        "parent_b": _noeud_arbre(cle_api_val, enfant["parent_b_id"], vus) if enfant["parent_b_id"] else None,
    }


@app.get("/genome/arbre/{eid}", tags=["genome"])
def genome_arbre_lire(eid: str, _cle: str = Depends(cle_api)):
    noeud = _noeud_arbre(_cle, eid)
    if noeud is None:
        raise HTTPException(404, f"Enfant '{eid}' introuvable.")
    return noeud


@app.post("/spatial/mondes", tags=["spatial"])
def spatial_monde_creer(body: CreerMonde, _cle: str = Depends(cle_api)):
    """Génère et persiste un nouveau monde : maillage Voronoï, biomes/ressources
    dérivés d'un bruit cohérent. `seed` généré si absent (renvoyé dans la réponse,
    même (nb_cellules, seed) ⇒ même monde)."""
    seed = body.seed if body.seed is not None else Random().randrange(2**31)
    cellules = spatial.generer_monde(body.nb_cellules, seed)
    return stockage_spatial.creer_monde(_cle, cellules, seed)


@app.post("/spatial/mondes/{mid}/forker", tags=["spatial"])
def spatial_monde_forker(mid: str, _cle: str = Depends(cle_api)):
    """Clone un monde existant (cellules + enfants placés) sous un nouvel id
    indépendant. Le monde source n'est jamais modifié."""
    nouveau = stockage_spatial.forker_monde(_cle, mid)
    if nouveau is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return nouveau


@app.get("/spatial/mondes", tags=["spatial"])
def spatial_mondes_lister(_cle: str = Depends(cle_api)):
    return stockage_spatial.lister_mondes(_cle)


@app.get("/spatial/mondes/{mid}", tags=["spatial"])
def spatial_monde_lire(mid: str, _cle: str = Depends(cle_api)):
    monde = stockage_spatial.lire_monde(_cle, mid)
    if monde is None:
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
    return monde


@app.get("/spatial/mondes/{mid}/cellules/{cid}", tags=["spatial"])
def spatial_cellule_lire(mid: str, cid: int, _cle: str = Depends(cle_api)):
    cellule = stockage_spatial.lire_cellule(_cle, mid, cid)
    if cellule is None:
        raise HTTPException(404, f"Cellule '{cid}' du monde '{mid}' introuvable.")
    return cellule


@app.delete("/spatial/mondes/{mid}", status_code=204, tags=["spatial"])
def spatial_monde_supprimer(mid: str, _cle: str = Depends(cle_api)):
    if not stockage_spatial.supprimer_monde(_cle, mid):
        raise HTTPException(404, f"Monde '{mid}' introuvable.")
