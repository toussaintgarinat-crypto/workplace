"""S228 : table entretiens (état de l'entretien guidé IA)."""
from app.models.manual import Entretiens


def test_entretiens_a_les_bonnes_colonnes():
    colonnes = set(Entretiens.__table__.columns.keys())
    assert colonnes == {
        "id", "venture_id", "section_courante", "sections_couvertes",
        "transcript", "statut", "sync_erreur", "derniere_activite", "created_at",
    }


def test_entretiens_tablename():
    assert Entretiens.__tablename__ == "entretiens"
