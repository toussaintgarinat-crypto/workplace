"""Tests de persistance du parc de calcul.

Stratégie : tout est hors-ligne ; on ne touche jamais /data. Les fichiers sont
créés dans tmp_path (pytest) et CALCUL_PARC_FILE est monkeypatché pour chaque
test. conftest.py pointe CALCUL_PARC_FILE sur un chemin inexistant par défaut
afin que les tests existants (test_api.py) ne voient jamais un parc-fichier
parasite.
"""
import json

import pytest

import noeud as N
import persistance as P


# ── Helpers ───────────────────────────────────────────────────────────────────
def _noeud(nid, endpoint="http://x:1", **kw):
    return N.Noeud(id=nid, endpoint=endpoint, **kw)


def _fichier(tmp_path, items: list) -> str:
    p = tmp_path / "noeuds.json"
    p.write_text(json.dumps(items), encoding="utf-8")
    return str(p)


# ── from_dict / to_dict ────────────────────────────────────────────────────────
def test_from_dict_basique():
    d = {"id": "m", "endpoint": "http://x:1234", "nom": "Mac"}
    n = N.Noeud.from_dict(d)
    assert n.id == "m" and n.endpoint == "http://x:1234" and n.nom == "Mac"


def test_from_dict_normalisations():
    d = {"id": "m", "endpoint": "http://x:1/", "methode_reveil": "wol", "sondes": "/v1/models"}
    n = N.Noeud.from_dict(d)
    assert n.endpoint == "http://x:1"
    assert n.methode_reveil == ("wol",)
    assert n.sondes == ("/v1/models",)


def test_from_dict_incomplet_leve():
    with pytest.raises(ValueError):
        N.Noeud.from_dict({"id": "m"})            # sans endpoint
    with pytest.raises(ValueError):
        N.Noeud.from_dict({"endpoint": "http://x"})  # sans id
    with pytest.raises(ValueError):
        N.Noeud.from_dict("pas un dict")


def test_to_dict_rondtrip():
    n = N.Noeud(id="m", endpoint="http://x:1", nom="Mac", mac_wol="AA:BB:CC:DD:EE:FF",
                methode_reveil=("wol",), sondes=("/v1/models",), priorite=5,
                modele_gateway="ollama/llama3")
    d = n.to_dict()
    n2 = N.Noeud.from_dict(d)
    assert n2.id == n.id
    assert n2.endpoint == n.endpoint
    assert n2.mac_wol == n.mac_wol
    assert n2.methode_reveil == n.methode_reveil
    assert n2.priorite == n.priorite
    assert n2.modele_gateway == n.modele_gateway


# ── charger_parc : env seul ────────────────────────────────────────────────────
def test_charger_parc_env_seul(monkeypatch, tmp_path):
    monkeypatch.setenv("CALCUL_PARC_FILE", str(tmp_path / "inexistant.json"))
    monkeypatch.setenv("CALCUL_NOEUDS", json.dumps([{"id": "a", "endpoint": "http://a:1"}]))
    parc = P.charger_parc()
    assert set(parc) == {"a"}


# ── charger_parc : fichier seul ────────────────────────────────────────────────
def test_charger_parc_fichier_seul(monkeypatch, tmp_path):
    chemin = _fichier(tmp_path, [{"id": "b", "endpoint": "http://b:1"}])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    monkeypatch.setenv("CALCUL_NOEUDS", "")
    parc = P.charger_parc()
    assert set(parc) == {"b"}


# ── charger_parc : fusion env + fichier ──────────────────────────────────────
def test_charger_parc_fusion(monkeypatch, tmp_path):
    chemin = _fichier(tmp_path, [{"id": "b", "endpoint": "http://b:1"}])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    monkeypatch.setenv("CALCUL_NOEUDS", json.dumps([{"id": "a", "endpoint": "http://a:1"}]))
    parc = P.charger_parc()
    assert set(parc) == {"a", "b"}


# ── charger_parc : fichier prioritaire sur env pour même id ──────────────────
def test_charger_parc_fichier_prioritaire(monkeypatch, tmp_path):
    chemin = _fichier(tmp_path, [{"id": "m", "endpoint": "http://fichier:9"}])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    monkeypatch.setenv("CALCUL_NOEUDS", json.dumps([{"id": "m", "endpoint": "http://env:9"}]))
    parc = P.charger_parc()
    assert parc["m"].endpoint == "http://fichier:9"


# ── charger_parc : fichier absent → tolérant ──────────────────────────────────
def test_charger_parc_fichier_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("CALCUL_PARC_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("CALCUL_NOEUDS", json.dumps([{"id": "a", "endpoint": "http://a:1"}]))
    parc = P.charger_parc()
    assert set(parc) == {"a"}      # env seul, pas d'erreur


# ── charger_parc : fichier corrompu → tolérant ────────────────────────────────
def test_charger_parc_fichier_illisible(monkeypatch, tmp_path):
    p = tmp_path / "corrompu.json"
    p.write_text("{pas du json", encoding="utf-8")
    monkeypatch.setenv("CALCUL_PARC_FILE", str(p))
    monkeypatch.setenv("CALCUL_NOEUDS", json.dumps([{"id": "a", "endpoint": "http://a:1"}]))
    parc = P.charger_parc()
    assert set(parc) == {"a"}     # env seul, pas d'erreur malgré fichier corrompu


# ── charger_parc : nœuds incomplets dans le fichier → ignorés ────────────────
def test_charger_parc_fichier_noeuds_incomplets(monkeypatch, tmp_path):
    items = [
        {"id": "ok", "endpoint": "http://ok:1"},
        {"endpoint": "http://sans-id:1"},          # ignoré : pas d'id
        {"id": "sans-endpoint"},                   # ignoré : pas d'endpoint
    ]
    chemin = _fichier(tmp_path, items)
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    monkeypatch.setenv("CALCUL_NOEUDS", "")
    parc = P.charger_parc()
    assert set(parc) == {"ok"}


# ── sauver_noeud : crée le fichier (upsert) ───────────────────────────────────
def test_sauver_noeud_cree_fichier(monkeypatch, tmp_path):
    chemin = str(tmp_path / "parc.json")
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    n = _noeud("m", "http://m:1")
    P.sauver_noeud(n)
    data = json.loads((tmp_path / "parc.json").read_text())
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["id"] == "m"


def test_sauver_noeud_upsert(monkeypatch, tmp_path):
    # Écrase un nœud existant avec le même id, conserve les autres
    chemin = _fichier(tmp_path, [
        {"id": "m", "endpoint": "http://m:1"},
        {"id": "autre", "endpoint": "http://autre:2"},
    ])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    n = _noeud("m", "http://m:99")
    P.sauver_noeud(n)
    data = json.loads((tmp_path / "noeuds.json").read_text())
    ids = {x["id"]: x for x in data}
    assert ids["m"]["endpoint"] == "http://m:99"
    assert "autre" in ids


# ── retirer_noeud ─────────────────────────────────────────────────────────────
def test_retirer_noeud_existant(monkeypatch, tmp_path):
    chemin = _fichier(tmp_path, [
        {"id": "a", "endpoint": "http://a:1"},
        {"id": "b", "endpoint": "http://b:1"},
    ])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    assert P.retirer_noeud("a") is True
    data = json.loads((tmp_path / "noeuds.json").read_text())
    assert [x["id"] for x in data] == ["b"]


def test_retirer_noeud_absent(monkeypatch, tmp_path):
    chemin = _fichier(tmp_path, [{"id": "a", "endpoint": "http://a:1"}])
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)
    assert P.retirer_noeud("fantome") is False


def test_retirer_noeud_fichier_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("CALCUL_PARC_FILE", str(tmp_path / "absent.json"))
    assert P.retirer_noeud("fantome") is False


# ── Tolérance aux éléments non-dict (S131 : fichier édité manuellement) ─────────
def test_sauver_noeud_tolere_parasite_non_dict(monkeypatch, tmp_path):
    """Un fichier contenant un élément parasite (string, int, null, etc.) ne plante pas."""
    chemin = str(tmp_path / "parc.json")
    # Fichier avec un parasite string en début et un nœud valide
    items = ["parasite", {"id": "ok", "endpoint": "http://ok:1"}]
    p = tmp_path / "parc.json"
    p.write_text(json.dumps(items), encoding="utf-8")
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)

    # sauver_noeud ne doit pas crasher et garder le nœud valide
    n = _noeud("nouveau", "http://nouveau:1")
    P.sauver_noeud(n)

    data = json.loads(p.read_text(encoding="utf-8"))
    # Le parasite a été jeté, le nœud valide et le nouveau présents
    assert [x["id"] for x in data if isinstance(x, dict)] == ["ok", "nouveau"]


def test_retirer_noeud_tolere_parasite_non_dict(monkeypatch, tmp_path):
    """retirer_noeud tolère aussi les parasites et les enlève lors de l'écriture."""
    chemin = str(tmp_path / "parc.json")
    # Fichier avec parasite et nœuds valides
    items = ["parasite", {"id": "a", "endpoint": "http://a:1"}, {"id": "b", "endpoint": "http://b:1"}]
    p = tmp_path / "parc.json"
    p.write_text(json.dumps(items), encoding="utf-8")
    monkeypatch.setenv("CALCUL_PARC_FILE", chemin)

    # Retirer le nœud "a" ne doit pas crasher
    assert P.retirer_noeud("a") is True

    data = json.loads(p.read_text(encoding="utf-8"))
    # Le parasite a été jeté, seul "b" reste
    assert [x["id"] for x in data] == ["b"]
