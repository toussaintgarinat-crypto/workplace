"""Tests du registre PROVIDER-AGNOSTIQUE : ordre, disponibilité, souveraineté par défaut."""
import fournisseurs as f


def test_registre_complet():
    assert set(f.REGISTRE) == {"local", "openai", "deepgram", "assemblyai", "gateway"}


def test_ordre_defaut_souverain_dabord():
    # SOUVERAIN d'abord : `local` est en tête de l'ordre par défaut.
    assert f.ordre()[0] == "local"
    assert f.ordre() == f.ORDRE_DEFAUT


def test_aucun_fournisseur_configure_par_defaut(monkeypatch):
    # conftest a tout coupé : aucun moteur disponible → mode placeholder.
    assert f.disponibles() == []


def test_ordre_surcharge_par_env(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDERS", "gateway, local , inconnu")
    # l'ordre est filtré sur les fournisseurs connus (inconnu ignoré).
    assert f.ordre() == ["gateway", "local"]


def test_cle_rend_fournisseur_disponible(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert "openai" in f.disponibles()
    assert f.REGISTRE["openai"].disponible() is True


def test_local_desactivable_par_env(monkeypatch):
    # Même si faster-whisper était installé, TRANSCRIPTION_LOCAL=0 le coupe (cf. conftest).
    assert f.REGISTRE["local"].disponible() is False


def test_texte_de_segments():
    segs = [{"texte": "Bonjour"}, {"texte": " tout le monde "}, {"texte": ""}]
    assert f._texte_de_segments(segs) == "Bonjour tout le monde"
