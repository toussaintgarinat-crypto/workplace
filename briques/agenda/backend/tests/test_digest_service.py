from services.digest import composer


def test_composer_quotidien_liste_events():
    events = [{"titre": "Dentiste", "debut": "2026-07-16T09:00", "calendrier": "Perso"},
              {"titre": "Réunion", "debut": "2026-07-16T14:00", "calendrier": "Boulot"}]
    d = composer("Marina", events, "quotidien")
    assert "jour" in d["sujet"].lower()
    assert "Dentiste" in d["texte"] and "Réunion" in d["texte"]
    assert "Dentiste" in d["html"] and "<" in d["html"]     # html balisé
    assert "Marina" in d["html"]


def test_composer_vide():
    d = composer("Marina", [], "quotidien")
    assert "Rien" in d["texte"]


def test_composer_hebdo_sujet():
    d = composer("Marina", [], "hebdo")
    assert "semaine" in d["sujet"].lower()
