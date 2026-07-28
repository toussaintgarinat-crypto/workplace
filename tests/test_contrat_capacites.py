"""Filet « contrat manifeste ↔ route » (S210) — ce que le manifeste promet, la route le tient.

Le Cœur transforme chaque `capacites[]` d'un `briques/<nom>/manifest.json` en outil pour
l'assistant : `params` devient le schéma que le LLM remplit, puis `core/outils_communs.py`
(`_appel_dynamique`) substitue les `{placeholders}` du `chemin` et envoie le reste en corps
JSON (ou en query pour un GET). Donc :

  • un `param` déclaré que la route n'accepte pas est **ignoré en silence** — l'assistant
    croit filtrer, classer, renommer, et il ne se passe rien ;
  • un champ **requis** par la route mais absent des `params` est **impossible à remplir**
    pour le LLM → 422 systématique, capacité morte depuis son écriture.

Jusqu'à S210 rien ne vérifiait ce contrat : `test_briques_smoke.py` ne regardait que la
présence d'un `nom`. Le scan a trouvé 11 capacités en écart, dont trois MORTES
(`connexion_envoyer`, `donnees_modifier`, `donnees_supprimer`, `transcription_fichier`).

Ce filet **importe** la brique et lit la vraie signature FastAPI (dépendances, modèle
Pydantic du corps) : un grep sur le fichier sur-signale (le mot existe ailleurs) et
sous-signale (query params non déclarés). Il coûte l'import de ~35 apps, ce qui reste
sous la seconde par brique et ne touche pas le réseau.

Limite assumée : une route dont le corps est un `dict` libre (`corps: dict = Body(...)`,
motif des proxys de `forge`) n'expose aucun schéma introspectable — ses `params` déclarés
sont acceptés sans vérification. Les champs requis hors-corps y restent contrôlés.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

# Importés AVANT toute brique, et jamais retirés de `sys.modules` (cf. `_charger_app`) :
# si `fastapi` était chargé PAR une brique puis déchargé, la brique suivante en obtiendrait
# une copie fraîche et `isinstance(route, APIRoute)` deviendrait faux pour la précédente —
# on croirait ses routes disparues (piège vécu en écrivant ce filet).
APIRoute = pytest.importorskip("fastapi.routing").APIRoute
BaseModel = pytest.importorskip("pydantic").BaseModel

RACINE = Path(__file__).resolve().parent.parent
BRIQUES_DIR = RACINE / "briques"

# Secrets factices : plusieurs briques lisent leur configuration à l'import (coffre,
# Gateway). Valeurs sans effet — aucune connexion n'est ouverte pendant un import.
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

# Les briques créent leurs dossiers de données à l'import (`/data/...`), chemin qui
# n'existe que dans leur conteneur. On redirige chaque défaut vers un dossier jetable,
# en le déduisant du code source : une brique qui ajoute une variable est couverte sans
# qu'on ait à tenir une liste à jour ici.
_TMP = Path(tempfile.mkdtemp(prefix="contrat-capacites-"))
_RE_CHEMIN_DEFAUT = re.compile(
    r"""(?:getenv|environ\.get)\(\s*["'](\w+)["']\s*,\s*["'](/[a-z]+[^"']*)["']""")
_RACINES_CONTENEUR = {"data", "clips", "fichiers", "audio", "modeles", "app", "srv", "var"}


def _manifests():
    return sorted(BRIQUES_DIR.glob("*/manifest.json"))


def _charger_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _cas():
    """(chemin du manifest, capacité) pour chaque capacité déclarée du parc."""
    cas = []
    for path in _manifests():
        for cap in _charger_manifest(path).get("capacites", []):
            cas.append((path, cap))
    return cas


def _id_cas(valeur):
    if isinstance(valeur, Path):
        return valeur.parent.name
    return valeur.get("nom", "?") if isinstance(valeur, dict) else str(valeur)


def _neutraliser_chemins_conteneur(dossier: Path):
    for py in dossier.rglob("*.py"):
        try:
            src = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for var, defaut in _RE_CHEMIN_DEFAUT.findall(src):
            if defaut.split("/")[1] in _RACINES_CONTENEUR:
                cible = _TMP / dossier.name / defaut.lstrip("/")
                cible.parent.mkdir(parents=True, exist_ok=True)
                os.environ[var] = str(cible)


_apps: dict = {}


def _charger_app(dossier: Path):
    """Importe la brique et renvoie son `app` FastAPI. Résultat mémorisé (et ses échecs).

    L'import se fait avec le dossier de la brique en tête de `sys.path` (les briques
    s'importent entre modules à plat : `import stockage`), puis on retire du cache les
    modules VENUS DE LA BRIQUE : plusieurs briques ont des modules homonymes (`stockage`,
    `prompts`, `agents`, `routers`) et `sys.modules` ferait charger le mauvais fichier à
    la suivante. Les paquets tiers (fastapi, sqlalchemy…) restent chargés.
    """
    if dossier.name in _apps:
        return _apps[dossier.name]
    for rel in ("main.py", "backend/main.py"):
        main = dossier / rel
        if main.exists():
            break
    else:
        resultat = (None, "aucun main.py — brique sans code Python")
        _apps[dossier.name] = resultat
        return resultat
    _neutraliser_chemins_conteneur(dossier)
    chemins = [str(main.parent)]
    if (dossier / "shared").is_dir():      # paquet vendored (agenda)
        chemins.append(str(dossier / "shared"))
    for c in chemins:
        sys.path.insert(0, c)
    connus = set(sys.modules)
    try:
        spec = importlib.util.spec_from_file_location(
            f"brique_{dossier.name.replace('-', '_')}", main)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        resultat = (getattr(module, "app", None), None)
    except ModuleNotFoundError as e:
        # Dépendance tierce absente de CET environnement (numpy, markdown…). La brique
        # est vérifiée dans son conteneur (`scripts/tests_briques.sh`) ; ici on le dit.
        resultat = (None, f"dépendance absente : {e.name}")
    finally:
        for nom in set(sys.modules) - connus:
            fichier = getattr(sys.modules.get(nom), "__file__", None)
            if fichier is None or any(fichier.startswith(c) for c in chemins):
                sys.modules.pop(nom, None)
        for c in chemins:
            sys.path.remove(c)
    _apps[dossier.name] = resultat
    return resultat


def _contrat_de_route(route):
    """(acceptés, requis, corps_opaque) tels que la route les voit réellement.

    Les paramètres de chemin du CODE sont ignorés à dessein : le Cœur substitue les
    placeholders du `chemin` du MANIFESTE, par position. Que la route nomme `{did}` ce
    que le manifeste appelle `{id}` est sans effet ; ce sont les placeholders déclarés
    qui doivent figurer dans `params` (vérifié par l'appelant).
    """
    dep = route.dependant
    acceptes, requis, opaque = set(), set(), False
    for champ in dep.query_params:
        acceptes.add(champ.alias or champ.name)
        if champ.required:
            requis.add(champ.alias or champ.name)
    for champ in dep.header_params + dep.cookie_params:
        acceptes.add(champ.alias or champ.name)
    # Sous-dépendances (auth, identité) : acceptées, jamais exigées du manifeste — un
    # en-tête `X-API-Key` est posé par le Cœur, pas rempli par le LLM.
    pile = list(dep.dependencies)
    while pile:
        sous = pile.pop()
        for champ in sous.query_params + sous.header_params + sous.cookie_params:
            acceptes.add(champ.alias or champ.name)
        pile.extend(sous.dependencies)
    if route.body_field is not None:
        modele = getattr(route.body_field, "type_", None)
        if isinstance(modele, type) and issubclass(modele, BaseModel):
            for nom, champ in modele.model_fields.items():
                acceptes.add(champ.alias or nom)
                if champ.is_required():
                    requis.add(champ.alias or nom)
        else:
            for champ in dep.body_params:
                annotation = champ.field_info.annotation
                if annotation is dict or getattr(annotation, "__origin__", None) is dict:
                    opaque = True          # `corps: dict = Body(...)` — aucun schéma
                else:
                    acceptes.add(champ.alias or champ.name)
                    if champ.required:
                        requis.add(champ.alias or champ.name)
    return acceptes, requis, opaque


def _route_de(app, capacite):
    def normaliser(chemin):
        return re.sub(r"\{[^}]*\}", "{}", chemin)

    methode = capacite["methode"].upper()
    cible = normaliser(capacite["chemin"])
    for route in app.routes:
        if isinstance(route, APIRoute) and methode in route.methods:
            if normaliser(route.path) == cible:
                return route
    return None


def _app_ou_skip(path):
    app, motif = _charger_app(path.parent)
    if app is None:
        pytest.skip(f"{path.parent.name} : {motif}")
    return app


@pytest.mark.parametrize("path,capacite", _cas(), ids=_id_cas)
def test_capacite_pointe_sur_une_route_existante(path, capacite):
    """Un `chemin`/`methode` sans route = 404 à chaque appel (piège : un segment oublié)."""
    app = _app_ou_skip(path)
    assert _route_de(app, capacite) is not None, (
        f"{path.parent.name} / {capacite['nom']} : aucune route "
        f"{capacite['methode'].upper()} {capacite['chemin']}")


@pytest.mark.parametrize("path,capacite", _cas(), ids=_id_cas)
def test_params_declares_existent_dans_la_route(path, capacite):
    """Un param que la route n'accepte pas est ignoré en silence (le pire des bugs)."""
    app = _app_ou_skip(path)
    route = _route_de(app, capacite)
    if route is None:
        pytest.skip("route absente — cf. test_capacite_pointe_sur_une_route_existante")
    acceptes, _, opaque = _contrat_de_route(route)
    if opaque:
        pytest.skip("corps `dict` libre : aucun schéma à confronter")
    acceptes |= set(re.findall(r"\{([^}]+)\}", capacite["chemin"]))
    fantomes = sorted(set((capacite.get("params") or {})) - acceptes)
    assert not fantomes, (
        f"{path.parent.name} / {capacite['nom']} : param(s) déclaré(s) que "
        f"{capacite['methode'].upper()} {capacite['chemin']} n'accepte pas : {fantomes}. "
        f"Acceptés : {sorted(acceptes)}")


@pytest.mark.parametrize("path,capacite", _cas(), ids=_id_cas)
def test_champs_requis_sont_declares(path, capacite):
    """Un champ requis absent des `params` = le LLM ne peut pas le remplir → 422 garanti."""
    app = _app_ou_skip(path)
    route = _route_de(app, capacite)
    if route is None:
        pytest.skip("route absente — cf. test_capacite_pointe_sur_une_route_existante")
    _, requis, _ = _contrat_de_route(route)
    requis |= set(re.findall(r"\{([^}]+)\}", capacite["chemin"]))
    manquants = sorted(requis - set(capacite.get("params") or {}))
    assert not manquants, (
        f"{path.parent.name} / {capacite['nom']} : champ(s) requis par "
        f"{capacite['methode'].upper()} {capacite['chemin']} et non déclaré(s) : "
        f"{manquants}")
