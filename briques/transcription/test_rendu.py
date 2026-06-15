"""Tests du rendu (pur) : paquet normalisé, slug sûr, Markdown."""
import rendu


def test_paquet_normalise():
    p = rendu.paquet({"resume": "r", "points_action": ["a"], "themes": ["t"],
                      "decisions": ["d"], "source": "llm"},
                     {"texte": "transcription", "langue": "fr", "backend": "local"},
                     titre="Réunion")
    assert p["titre"] == "Réunion"
    assert p["resume"] == "r" and p["points_action"] == ["a"]
    assert p["langue"] == "fr" and p["transcription"] == "transcription"
    assert p["source_notes"] == "llm" and p["backend_transcription"] == "local"
    assert p["date"]                                  # date posée automatiquement


def test_paquet_titre_par_defaut():
    p = rendu.paquet({}, {})
    assert p["titre"].startswith("Notes du ")


def test_slug_sur():
    assert rendu.slug("Réunion client — 14h !") == "reunion-client-14h"
    assert rendu.slug("../../etc/passwd") == "etc-passwd"     # pas de traversée
    assert rendu.slug("") == "notes"


def test_markdown_sections():
    p = rendu.paquet({"resume": "Synthèse.", "points_action": ["faire X"],
                      "themes": ["budget"], "decisions": ["valider Y"]},
                     {"texte": "le texte brut"}, titre="Titre")
    md = rendu.markdown(p)
    assert md.startswith("# Titre")
    assert "## Résumé" in md and "Synthèse." in md
    assert "- [ ] faire X" in md                       # points d'action = cases à cocher
    assert "## Décisions" in md and "- valider Y" in md
    assert "budget" in md and "le texte brut" in md


def test_markdown_omet_sections_vides():
    md = rendu.markdown(rendu.paquet({"resume": "juste un résumé"}, {}, titre="T"))
    assert "## Résumé" in md
    assert "## Points d'action" not in md              # rien → section absente
    assert "## Transcription" not in md
