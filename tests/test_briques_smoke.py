"""Filet « santé briques » (S116) — validation HORS-LIGNE du contrat de manifest.

Le Cœur découvre chaque brique via son `briques/<nom>/manifest.json` (cf.
`core/registre.py`). Si un manifest est malformé, sans port, ou en collision de port
avec une autre brique, le Cœur charge mal ou route mal — sans qu'aucun test unitaire
de brique ne le voie. Ce smoke garde ce contrat partagé : il tourne partout (pur
stdlib, aucune dépendance de brique, aucun réseau), et sert de net AVANT les sprints
inter-briques (auth unifiée S120, multi-tenant S121).
"""
import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
BRIQUES_DIR = RACINE / "briques"

# Champs que le Cœur (registre + dashboard + horloge) suppose présents sur CHAQUE brique.
CHAMPS_REQUIS = ("nom", "version", "description", "role", "couche", "statut")
# Le contrat réseau (port + endpoint de santé) n'est exigé que des briques de SERVICE
# (couche backend) : une brique frontend peut être un HTML statique (port null, ex.
# app-builder) ou servir son UI sur un port et sonder un backend sur un autre (ex. oria).
CHAMPS_RESEAU = ("port", "url_sante")
STATUTS_CONNUS = {"actif", "setup_requis", "a_tester", "inactif"}


def _manifests():
    return sorted(BRIQUES_DIR.glob("*/manifest.json"))


def _charger(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_repertoire_briques_existe():
    assert BRIQUES_DIR.is_dir(), f"Répertoire des briques introuvable : {BRIQUES_DIR}"
    assert _manifests(), "Aucun manifest.json trouvé sous briques/*/"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_manifest_est_un_json_valide(path):
    """Un manifest illisible casse silencieusement le chargement du registre."""
    _charger(path)  # lève si JSON invalide


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_manifest_porte_les_champs_requis(path):
    data = _charger(path)
    manquants = [c for c in CHAMPS_REQUIS if c not in data or data[c] in (None, "")]
    assert not manquants, f"{path.parent.name} : champs requis manquants {manquants}"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_brique_backend_porte_le_contrat_reseau(path):
    """Toute brique de service (couche backend) doit déclarer port + url_sante."""
    data = _charger(path)
    if data.get("couche") != "backend":
        pytest.skip("brique non-backend : contrat réseau optionnel")
    manquants = [c for c in CHAMPS_RESEAU if c not in data or data[c] in (None, "")]
    assert not manquants, f"{path.parent.name} (backend) : {manquants} manquant(s)"


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_statut_est_connu(path):
    data = _charger(path)
    assert data["statut"] in STATUTS_CONNUS, (
        f"{path.parent.name} : statut inconnu « {data['statut']} » "
        f"(attendus : {sorted(STATUTS_CONNUS)})")


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_url_sante_contient_le_port(path):
    """Pour une brique backend, url_sante doit pointer sur le port déclaré (sinon le
    dashboard sonde dans le vide). Les frontends sont exemptés (cf. oria/app-builder)."""
    data = _charger(path)
    if data.get("couche") != "backend" or not data.get("port") or not data.get("url_sante"):
        pytest.skip("contrat réseau non applicable (non-backend ou champs absents)")
    assert str(data["port"]) in data["url_sante"], (
        f"{path.parent.name} : url_sante « {data['url_sante']} » "
        f"n'encode pas le port {data['port']}")


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_capacites_et_taches_bien_formees(path):
    """Capacités et tâches (optionnelles) doivent porter les clés que le Cœur lit."""
    data = _charger(path)
    for cap in data.get("capacites", []):
        assert cap.get("nom"), f"{path.parent.name} : une capacité sans 'nom' : {cap}"
    for tache in data.get("taches", []):
        for cle in ("nom", "methode", "chemin"):
            assert tache.get(cle), (
                f"{path.parent.name} : tâche sans '{cle}' : {tache}")


def test_noms_de_briques_uniques():
    noms = [_charger(p).get("nom") for p in _manifests()]
    doublons = sorted({n for n in noms if noms.count(n) > 1})
    assert not doublons, f"Noms de briques en double : {doublons}"


def test_aucune_collision_de_port():
    """Deux briques sur le même port = l'une masque l'autre au lancement (piège connu)."""
    par_port = {}
    for p in _manifests():
        data = _charger(p)
        par_port.setdefault(data["port"], []).append(data.get("nom"))
    collisions = {port: noms for port, noms in par_port.items() if len(noms) > 1}
    assert not collisions, f"Collisions de port : {collisions}"


# ── S207 : convention de santé ──────────────────────────────────────────────
# `/sante` est la convention du parc (35 manifests sur 38 la suivaient déjà). Le Cœur, lui,
# ne répondait qu'à `/health` : une sonde écrite de bonne foi tombait à côté et le croyait
# muet — c'est arrivé pendant l'audit du 2026-07-27. Les deux briques restées sur `/health`
# servent désormais AUSSI `/sante`, sans que l'ancien chemin disparaisse (healthchecks Docker
# et oria-stack pointent dessus).
#
# `gateway` est la seule exception admise : c'est l'image officielle LiteLLM, dont on ne peut
# pas ajouter de route. Elle est nommée ici pour que l'exception reste un choix explicite et
# non un oubli qui se propage.
EXCEPTIONS_SANTE = {"gateway"}


@pytest.mark.parametrize("path", _manifests(), ids=lambda p: p.parent.name)
def test_convention_url_sante(path):
    data = _charger(path)
    nom = path.parent.name
    if data.get("couche") != "backend" or not data.get("url_sante"):
        pytest.skip("contrat réseau non applicable")
    if nom in EXCEPTIONS_SANTE:
        pytest.skip(f"{nom} : exception admise (image tierce, route non modifiable)")
    chemin = data["url_sante"].split("/", 3)[-1]
    assert chemin.startswith(("sante", "health")), (
        f"{nom} : url_sante « {data['url_sante']} » ne suit aucune convention connue")
