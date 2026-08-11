"""S228 : entretien guidé IA."""
from __future__ import annotations

from types import SimpleNamespace

import app.routers.entretiens as entretiens_mod
from app.serde import entretien


def test_squelette_a_9_qualitatif_et_4_processus():
    familles = [s["famille"] for s in entretiens_mod.SECTIONS]
    assert familles.count("qualitatif") == 9
    assert familles.count("processus") == 4
    assert len(entretiens_mod.SECTIONS) == 13


def test_squelette_categories_qualitatif_s227():
    cats = {s["categorie"] for s in entretiens_mod.SECTIONS if s["famille"] == "qualitatif"}
    assert cats == {
        "organisation", "activites", "clients", "fournisseurs", "outils_utilises",
        "personnel", "contraintes", "objectifs", "problemes_connus",
    }


def test_prochaine_section_renvoie_la_premiere_non_couverte():
    premiere = entretiens_mod.SECTIONS[0]["id"]
    deuxieme = entretiens_mod.SECTIONS[1]["id"]
    assert entretiens_mod._prochaine_section([])["id"] == premiere
    assert entretiens_mod._prochaine_section([premiere])["id"] == deuxieme


def test_prochaine_section_renvoie_none_si_squelette_complet():
    tous = [s["id"] for s in entretiens_mod.SECTIONS]
    assert entretiens_mod._prochaine_section(tous) is None


def test_serde_entretien_camel_case():
    r = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        venture_id="22222222-2222-2222-2222-222222222222",
        section_courante="qualitatif.organisation",
        sections_couvertes=["qualitatif.activites"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=None, created_at=None,
    )
    d = entretien(r)
    assert d["sectionCourante"] == "qualitatif.organisation"
    assert d["sectionsCouvertes"] == ["qualitatif.activites"]
    assert d["ventureId"] == "22222222-2222-2222-2222-222222222222"
    assert d["statut"] == "en_cours"
    assert d["syncErreur"] is None
