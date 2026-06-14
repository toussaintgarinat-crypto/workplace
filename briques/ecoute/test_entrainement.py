"""Tests de la file d'entraînement (S43) — hors ligne, entraîneur en stand-in injecté.

On NE dépend ni d'openWakeWord ni d'un GPU : la source du stand-in est un fichier
quelconque injecté (`source_standin`), ce qui prouve le *câblage* livraison→sélection
sans prétendre entraîner un vrai modèle (cf. honnêteté `entrainement.py`).
"""
import pytest

import commandes as cmd
import entrainement


@pytest.fixture
def magasin(tmp_path):
    m = cmd.MagasinCommandes(db=str(tmp_path / "t.db"))
    m.init_db()
    return m


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src.onnx"
    src.write_bytes(b"\x00fake-onnx")
    return src


def test_entrainer_standin_marque_factice(tmp_path, source):
    commande = {"modele": "acme", "nom_marque": "Acme", "factice": False}
    res = entrainement.entrainer(commande, base_modeles=str(tmp_path / "m"),
                                 source_standin=source)
    assert res["ok"] and res["factice"] is True
    assert entrainement.modele_livre("acme", str(tmp_path / "m"))


def test_entrainer_idempotent(tmp_path, source):
    base = str(tmp_path / "m")
    commande = {"modele": "acme", "nom_marque": "Acme", "factice": False}
    entrainement.entrainer(commande, base_modeles=base, source_standin=source)
    res = entrainement.entrainer(commande, base_modeles=base, source_standin=source)
    assert res["ok"] and "idempotent" in res["message"].lower()


def test_entrainer_sans_source_ni_cmd_echoue(tmp_path, monkeypatch):
    monkeypatch.setattr(entrainement, "ENTRAINEUR_CMD", None)
    monkeypatch.delenv("MODELE_SOURCE_STANDIN", raising=False)
    commande = {"modele": "zzz", "nom_marque": "Zzz", "factice": False}
    # source_standin=None ET pas d'openwakeword importable depuis le venv de test → échec honnête
    res = entrainement.entrainer(commande, base_modeles=str(tmp_path / "m"),
                                 source_standin=tmp_path / "absent.onnx")
    assert res["ok"] is False


def test_traiter_file_cycle_complet(tmp_path, magasin, source):
    """payee → (une passe) → livrée, et le modèle devient livré (sélectionnable)."""
    base = str(tmp_path / "m")
    c = magasin.creer("Acme")
    magasin.marquer_payee(c["id"])
    rapport = entrainement.traiter_file(magasin, base_modeles=base, source_standin=source)
    assert c["id"] in rapport["avancees"]
    assert c["id"] in rapport["livrees"]
    final = magasin.get(c["id"])
    assert final["statut"] == "livree" and final["factice"] == 1
    assert entrainement.modele_livre("acme", base)


def test_traiter_file_relance_impayee_bornee(tmp_path, magasin, source, monkeypatch):
    monkeypatch.setattr(entrainement, "RELANCES_MAX", 2)
    c = magasin.creer("Acme")  # reste en_attente_paiement
    for _ in range(5):
        entrainement.traiter_file(magasin, base_modeles=str(tmp_path / "m"), source_standin=source)
    # relances plafonnées (rappel poli, pas de spam)
    assert magasin.get(c["id"])["relances"] == 2
    assert magasin.get(c["id"])["statut"] == "en_attente_paiement"


def test_traiter_file_echec_sans_modele(tmp_path, magasin, monkeypatch):
    monkeypatch.setattr(entrainement, "ENTRAINEUR_CMD", None)
    c = magasin.creer("Acme")
    magasin.marquer_payee(c["id"])
    # pas de source → l'entraînement échoue honnêtement, la commande passe `echec`
    rapport = entrainement.traiter_file(magasin, base_modeles=str(tmp_path / "m"),
                                        source_standin=tmp_path / "absent.onnx")
    assert c["id"] in rapport["echecs"]
    assert magasin.get(c["id"])["statut"] == "echec"
