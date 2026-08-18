"""Tests — journal d'écoute/choix par profil (V1 saga familiale).

Motif calqué sur la persistance des profils (`_load_profil`/`_save_profil`) : un fichier
par profil, préfixé par le même id pour rester portable (ADR 2026-08-18)."""
import os
import pytest

import studio as A


@pytest.fixture(autouse=True)
def cleanup_journal_files():
    """Supprime les fichiers journaux avant chaque test pour isoler les cas."""
    for profil_id in ["p1", "p2", "p3", "p4", "abc123", "inexistant-xyz"]:
        journal_file = A._journal_path(profil_id)
        if os.path.exists(journal_file):
            os.remove(journal_file)
    yield
    # Cleanup après le test aussi
    for profil_id in ["p1", "p2", "p3", "p4", "abc123", "inexistant-xyz"]:
        journal_file = A._journal_path(profil_id)
        if os.path.exists(journal_file):
            os.remove(journal_file)


def test_journal_path_prefixe_par_profil_id():
    assert A._journal_path("abc123") == os.path.join(A.PROFILS_DIR, "abc123-journal.json")


def test_load_journal_absent_renvoie_liste_vide():
    assert A._load_journal("inexistant-xyz") == []


def test_ajouter_evenement_persiste_et_complete_id_quand():
    ev = A._ajouter_evenement("p1", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert ev["id"]
    assert ev["quand"]
    assert A._load_journal("p1") == [ev]


def test_ajouter_evenement_deux_fois_conserve_lordre():
    A._ajouter_evenement("p2", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    A._ajouter_evenement("p2", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 2})
    evenements = A._load_journal("p2")
    assert [e["episode_n"] for e in evenements] == [1, 2]


def test_journal_isole_entre_deux_profils():
    A._ajouter_evenement("p3", {"type": "chapitre_lu", "serie_id": "s1", "episode_n": 1})
    assert A._load_journal("p4") == []
