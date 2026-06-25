"""Tests de la bibliothèque de VOIX CLONÉES (S107) — CRUD pur + résolution + API.

Aucun moteur réel : Coqui est inerte en test (conftest coupe VOIX_COQUI), donc le rendu d'un
clone retombe sur le placeholder HONNÊTE. On vérifie le stockage, la validation, la résolution
de la convention `clone:<nom>`, et le câblage API (upload/list/delete/test + 404/422).
"""
import asyncio
import io
import wave

import clones
import moteur
import pytest


def _run(coro):
    return asyncio.run(coro)


def _wav(secondes: float = 1.5, cadence: int = 16000) -> bytes:
    """Petit WAV PCM silencieux valide (sert d'échantillon de référence en test)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(cadence)
        w.writeframes(b"\x00\x00" * int(secondes * cadence))
    return buf.getvalue()


# ── CRUD pur ──────────────────────────────────────────────────────

def test_enregistrer_et_lister(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    e = clones.enregistrer("Marina", _wav(2.0), notes="voix douce")
    assert e["slug"] == "marina" and e["nom"] == "Marina"
    assert e["duree_s"] >= 1.9 and e["notes"] == "voix douce"
    noms = [c["slug"] for c in clones.lister()]
    assert noms == ["marina"]


def test_chemin_existe_sur_disque(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    clones.enregistrer("Papi Jean", _wav())
    p = clones.chemin("Papi Jean")                     # résolution par nom lisible
    assert p and p.endswith("papi-jean.wav")
    assert clones.chemin("papi-jean")                  # ... ou par slug


def test_remplacer_meme_nom(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    clones.enregistrer("Marina", _wav(1.5))
    clones.enregistrer("Marina", _wav(3.0))            # ré-enregistrer écrase, pas de doublon
    items = clones.lister()
    assert len(items) == 1 and items[0]["duree_s"] >= 2.9


def test_supprimer(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    clones.enregistrer("Marina", _wav())
    assert clones.supprimer("Marina") is True
    assert clones.lister() == []
    assert clones.supprimer("Marina") is False         # déjà absente → False honnête


def test_refuse_non_wav(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        clones.enregistrer("X", b"ceci n'est pas un wav")


def test_refuse_trop_court(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        clones.enregistrer("X", _wav(0.2))


def test_refuse_nom_vide(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        clones.enregistrer("!!!", _wav())              # que des symboles → slug vide


def test_lister_robuste_si_index_corrompu(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    d = tmp_path / "voix-clonees"
    d.mkdir()
    (d / "voix-clonees.json").write_text("pas du json", encoding="utf-8")
    assert clones.lister() == []                       # repli honnête, pas d'exception


# ── Résolution de la convention clone:<nom> ───────────────────────

def test_est_reference_clone():
    assert clones.est_reference_clone("clone:marina")
    assert clones.est_reference_clone("CLONE:Marina")  # insensible à la casse
    assert not clones.est_reference_clone("alloy")
    assert not clones.est_reference_clone(None)


def test_resoudre_vers_chemin(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    clones.enregistrer("Marina", _wav())
    assert clones.resoudre("clone:Marina").endswith("marina.wav")
    assert clones.resoudre("clone:inconnue") is None
    assert clones.resoudre("alloy") is None


# ── Intégration moteur : un clone inconnu reste honnête ───────────

def test_moteur_clone_introuvable_placeholder(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    res = _run(moteur.synthetiser("Bonjour", "clone:fantome"))
    assert res["place_holder"] is True
    assert "introuvable" in res["note"].lower()


def test_moteur_clone_connu_mais_coqui_absent(monkeypatch, tmp_path):
    # Voix clonée présente, mais Coqui inerte en test → placeholder honnête (jamais un autre
    # timbre à la place), et le moteur a bien été FORCÉ sur coqui (aucun autre candidat).
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    clones.enregistrer("Marina", _wav())
    res = _run(moteur.synthetiser("Bonjour", "clone:Marina"))
    assert res["place_holder"] is True


# ── API (TestClient) : upload / liste / suppression / test ────────

def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    import main
    return TestClient(main.app)


def test_api_upload_liste_supprime(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/voix/clones", data={"nom": "Marina", "notes": "douce"},
               files={"fichier": ("v.wav", _wav(2.0), "audio/wav")})
    assert r.status_code == 200 and r.json()["clone"]["slug"] == "marina"

    r = c.get("/voix/clones")
    body = r.json()
    assert body["ok"] and [x["slug"] for x in body["clones"]] == ["marina"]
    assert body["coqui_disponible"] is False           # inerte en test, dit honnêtement

    assert c.delete("/voix/clones/Marina").status_code == 200
    assert c.get("/voix/clones").json()["clones"] == []


def test_api_upload_non_wav_422(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/voix/clones", data={"nom": "X"},
               files={"fichier": ("x.txt", b"pas un wav", "text/plain")})
    assert r.status_code == 422


def test_api_supprimer_inconnu_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.delete("/voix/clones/fantome").status_code == 404


def test_api_tester_inconnu_404(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/voix/clones/fantome/tester").status_code == 404


def test_api_tester_connu_placeholder(monkeypatch, tmp_path):
    # Coqui inerte → /tester rend un placeholder honnête (JSON), pas d'audio inventé.
    c = _client(monkeypatch, tmp_path)
    c.post("/voix/clones", data={"nom": "Marina"},
           files={"fichier": ("v.wav", _wav(), "audio/wav")})
    r = c.post("/voix/clones/Marina/tester")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["place_holder"] is True
