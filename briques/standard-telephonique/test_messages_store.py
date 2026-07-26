"""Tests messages_store : SQLite sur fichier temporaire, aucune dépendance externe."""
import tempfile
from pathlib import Path

import messages_store


def test_enregistrer_puis_lister():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "messages.db")

        id1 = messages_store.enregistrer(db_path, option="3", audio_path="/data/audio/a.wav",
                                         duree_s=12.5, texte="bonjour ceci est un test")
        id2 = messages_store.enregistrer(db_path, option=None, audio_path="/data/audio/b.wav",
                                         duree_s=4.0, texte=None)

        assert id1 != id2
        messages = messages_store.lister(db_path, limite=20)
        assert len(messages) == 2
        # le plus récent (id2) en premier
        assert messages[0]["id"] == id2
        assert messages[0]["option"] is None
        assert messages[0]["texte"] is None
        assert messages[1]["id"] == id1
        assert messages[1]["option"] == "3"
        assert messages[1]["texte"] == "bonjour ceci est un test"
        assert messages[1]["duree_s"] == 12.5


def test_lister_respecte_la_limite():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "messages.db")
        for i in range(5):
            messages_store.enregistrer(db_path, option=str(i), audio_path=f"/data/audio/{i}.wav",
                                       duree_s=1.0, texte=None)
        assert len(messages_store.lister(db_path, limite=3)) == 3


def test_lister_db_absente_renvoie_liste_vide():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "inexistant.db")
        assert messages_store.lister(db_path) == []


def test_mettre_a_jour_texte():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "messages.db")
        message_id = messages_store.enregistrer(db_path, option="2", audio_path="/data/audio/c.wav",
                                                 duree_s=8.0, texte=None)

        messages_store.mettre_a_jour_texte(db_path, message_id, "transcription arrivee apres coup")

        messages = messages_store.lister(db_path)
        assert messages[0]["texte"] == "transcription arrivee apres coup"
