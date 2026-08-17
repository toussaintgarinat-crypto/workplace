"""Tests — persistance des profils lecteurs (un fichier par profil, S231).

Motif calqué sur la persistance des séries (`_path`/`_load`/`_save`), dans un sous-dossier
dédié (`PROFILS_DIR`) pour ne jamais collisionner avec un fichier de série."""
import os

import pytest

import studio as A


def test_profils_dir_est_un_sous_dossier_de_ateliers_dir():
    assert A.PROFILS_DIR == os.path.join(A.ATELIERS_DIR, "profils")
    assert os.path.isdir(A.PROFILS_DIR)


def test_save_puis_load_roundtrip():
    profil = {"id": "abc123", "nom": "Fils", "cible": "7-9",
              "cree_par": "perso", "cree_le": "2026-08-17T00:00:00+00:00"}
    A._save_profil(profil)
    relu = A._load_profil("abc123")
    assert relu == profil


def test_load_profil_absent_leve_filenotfound():
    with pytest.raises(FileNotFoundError):
        A._load_profil("inexistant-xyz")


def test_profil_path_ne_collisionne_pas_avec_une_serie():
    # Un id de série est un uuid4 hex ; un profil du même id reste dans un sous-dossier distinct.
    assert A._profil_path("meme-id") != A._path("meme-id")
