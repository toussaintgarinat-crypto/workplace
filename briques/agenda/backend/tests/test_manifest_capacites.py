"""Test de DÉCOUVERTE (S168) : le manifest est le contrat que le Cœur lit pour piloter
l'agenda. On garantit que chaque capacité pointe une route RÉELLE de l'app (même méthode +
gabarit de chemin), que les noms sont uniques, que les 8 capacités attendues sont là, et
que la POLITIQUE DE GATES propre à l'agenda est respectée (divergence assumée vs S167 :
create/move/rappels/creer_partage en effet immédiat ; seuls supprimer + inviter gardés)."""

import json
import re
from pathlib import Path

# Toutes les capacités vivent sous /service (garanti par un test ci-dessous) : on
# assemble les routes réelles depuis CE routeur, sans monter l'app entière (`import main`
# tire la lib vendored + prometheus/redis, indisponibles nativement).
from routers.service import router as service_router

_MANIFEST = json.loads((Path(__file__).resolve().parents[2] / "manifest.json").read_text())
_CAPS = _MANIFEST["capacites"]


def _gabarit(chemin: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", chemin)


def _routes_reelles() -> set[tuple[str, str]]:
    routes = set()
    for r in service_router.routes:
        for methode in getattr(r, "methods", set()) or set():
            routes.add((methode, _gabarit(getattr(r, "path", ""))))
    return routes


def test_chaque_capacite_pointe_une_route_reelle():
    reelles = _routes_reelles()
    manquantes = [(c["nom"], c["methode"], c["chemin"]) for c in _CAPS
                  if (c["methode"], _gabarit(c["chemin"])) not in reelles]
    assert not manquantes, f"Capacités sans route correspondante : {manquantes}"


def test_toutes_les_capacites_sont_sous_service():
    # La surface pilotable est cloisonnée sous /service (auth S2S + contrat français).
    hors = [c["nom"] for c in _CAPS if not c["chemin"].startswith("/service")]
    assert not hors, f"Capacités hors de /service : {hors}"


def test_noms_de_capacites_uniques():
    noms = [c["nom"] for c in _CAPS]
    doublons = sorted({n for n in noms if noms.count(n) > 1})
    assert not doublons, f"Noms en double : {doublons}"


def test_les_capacites_attendues():
    attendues = {
        # Agenda (S168)
        "agenda_consulter", "agenda_lister", "agenda_creer_evenement",
        "agenda_definir_rappels", "agenda_deplacer_evenement",
        "agenda_supprimer_evenement", "agenda_creer_partage", "agenda_inviter",
        # Listes de courses/tâches (S176)
        "courses_consulter", "courses_creer_liste", "courses_ajouter", "courses_cocher",
    }
    assert {c["nom"] for c in _CAPS} == attendues


def test_politique_de_gates_agenda():
    """Divergence produit ASSUMÉE (cf. ADR) : seules 2 capacités sont gardées."""
    gardees = {c["nom"] for c in _CAPS if c["action"]}
    assert gardees == {"agenda_supprimer_evenement", "agenda_inviter"}, \
        f"Politique de gates inattendue : {gardees}"
