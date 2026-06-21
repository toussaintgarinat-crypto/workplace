"""S87 — fusion contrôlée : le gate humain qui rend l'atelier UTILE (ferme la boucle).

On prouve, sur un VRAI dépôt jetable (cf. conftest) et avec le mock honnête :
  • la fusion exige la revue + une confirmation explicite (effet de bord sur `main`) ;
  • après fusion, le travail est BIEN sur `main` (et `git revert`-able grâce à --no-ff) ;
  • une brique sensible (paiements/connexion/auth) est refusée sauf déblocage ;
  • un conflit n'est jamais forcé : il est remonté et le dépôt reste propre ;
  • le rebuild ciblé est SIMULÉ par défaut (honnête, aucune commande exécutée).
"""
import os
import subprocess

import domaine
import git_atelier
import pytest
import rebuild
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _git_main(*args):
    return subprocess.run(["git", "-C", git_atelier.REPO, *args],
                          capture_output=True, text=True).stdout


def _ouvrir_et_lancer(intention="ajouter une note", brique="mail"):
    r = client.post("/chantiers", json={"intention": intention, "brique_cible": brique,
                                        "agent": "factice"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.status_code == 200 and r.json()["statut"] == "revue"
    return cid


# ── Domaine pur ────────────────────────────────────────────────────────────────
def test_fusion_autorisee_brique_ordinaire():
    ok, bloquantes = domaine.fusion_autorisee(["mail", "agenda"])
    assert ok and bloquantes == []


def test_fusion_refuse_brique_sensible():
    ok, bloquantes = domaine.fusion_autorisee(["mail", "paiements"])
    assert not ok and bloquantes == ["paiements"]


def test_fusion_brique_sensible_debloquee():
    ok, bloquantes = domaine.fusion_autorisee(["paiements"], debloquees={"paiements"})
    assert ok and bloquantes == []


# ── Garde-fous de l'endpoint ─────────────────────────────────────────────────────
def test_fusion_exige_la_revue():
    r = client.post("/chantiers", json={"intention": "x", "agent": "factice"})
    cid = r.json()["id"]  # état `cree`, pas encore lancé
    r = client.post(f"/chantiers/{cid}/fusionner", json={"confirme": True})
    assert r.status_code == 409
    client.delete(f"/chantiers/{cid}")


def test_fusion_exige_confirmation():
    cid = _ouvrir_et_lancer()
    r = client.post(f"/chantiers/{cid}/fusionner", json={"confirme": False})
    assert r.status_code == 428
    client.delete(f"/chantiers/{cid}")


def test_fusion_refuse_brique_sensible_endpoint():
    cid = _ouvrir_et_lancer(intention="toucher le rail", brique="paiements")
    r = client.post(f"/chantiers/{cid}/fusionner", json={"confirme": True})
    assert r.status_code == 403
    assert "paiements" in r.json()["detail"]
    # Refus = main intact : la note factice n'est pas passée en prod.
    assert "ATELIER_DEV_NOTE.md" not in _git_main("ls-tree", "--name-only", "main")
    client.delete(f"/chantiers/{cid}")


# ── Le parcours qui ferme la boucle ──────────────────────────────────────────────
def test_fusion_complete_arrive_sur_main():
    cid = _ouvrir_et_lancer()
    avant = _git_main("rev-parse", "main").strip()
    try:
        r = client.post(f"/chantiers/{cid}/fusionner", json={"confirme": True})
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["statut"] == "fusionne"
        assert corps["briques_touchees"] == ["mail"]
        # Rebuild ciblé SIMULÉ par défaut (honnête) : commande journalisée, pas exécutée.
        assert corps["rebuilds"] and corps["rebuilds"][0]["reel"] is False
        assert "docker compose" in corps["rebuilds"][0]["commande"]

        # Le travail est BIEN sur main maintenant, et main a avancé d'un commit de fusion.
        apres = _git_main("rev-parse", "main").strip()
        assert apres != avant
        assert "ATELIER_DEV_NOTE.md" in _git_main("ls-tree", "--name-only", "-r", "main")

        # --no-ff → la fusion est un commit de merge relisible / revert-able.
        log = _git_main("log", "-1", "--pretty=%s", "main")
        assert "fusion" in log

        # Le worktree a été jeté, la branche supprimée (chantier clos).
        assert "dev/" not in _git_main("worktree", "list")
    finally:
        # Rollback honnête pour ne pas polluer les autres tests, même si une assertion casse.
        subprocess.run(["git", "-C", git_atelier.REPO, "reset", "--hard", avant],
                       capture_output=True, text=True)


def test_fusion_conflit_jamais_force():
    # Deux chantiers modifient la MÊME ligne du même fichier → conflit garanti au 2e merge.
    base = _git_main("rev-parse", "main").strip()
    chemin_prod = os.path.join(git_atelier.REPO, "README.md")

    c1 = git_atelier.ouvrir_chantier("dev/conflit-a")
    with open(os.path.join(git_atelier.ATELIERS, "dev-conflit-a", "README.md"), "w") as f:
        f.write("# Version A\n")
    subprocess.run(["git", "-C", os.path.join(git_atelier.ATELIERS, "dev-conflit-a"),
                    "commit", "-am", "A"], capture_output=True, text=True)

    c2 = git_atelier.ouvrir_chantier("dev/conflit-b")
    with open(os.path.join(git_atelier.ATELIERS, "dev-conflit-b", "README.md"), "w") as f:
        f.write("# Version B\n")
    subprocess.run(["git", "-C", os.path.join(git_atelier.ATELIERS, "dev-conflit-b"),
                    "commit", "-am", "B"], capture_output=True, text=True)

    # 1re fusion : OK.
    git_atelier.fusionner("dev/conflit-a")
    # 2e fusion : conflit → ErreurGit, et le dépôt reste PROPRE (merge avorté).
    with pytest.raises(git_atelier.ErreurGit):
        git_atelier.fusionner("dev/conflit-b")
    assert _git_main("status", "--porcelain").strip() == ""  # aucun conflit en suspens

    # Nettoyage : worktrees + retour à l'état initial.
    git_atelier.jeter_chantier("dev/conflit-a")
    git_atelier.jeter_chantier("dev/conflit-b")
    subprocess.run(["git", "-C", git_atelier.REPO, "reset", "--hard", base],
                   capture_output=True, text=True)


# ── Rebuild ciblé (module pur) ────────────────────────────────────────────────────
def test_briques_touchees_extrait_les_noms():
    branche = "dev/touche-mail"
    git_atelier.ouvrir_chantier(branche)
    wt = os.path.join(git_atelier.ATELIERS, domaine.slug(branche))
    os.makedirs(os.path.join(wt, "briques", "mail"), exist_ok=True)
    with open(os.path.join(wt, "briques", "mail", "x.py"), "w") as f:
        f.write("# touche\n")
    subprocess.run(["git", "-C", wt, "add", "-A"], capture_output=True, text=True)
    subprocess.run(["git", "-C", wt, "commit", "-m", "touche mail"], capture_output=True, text=True)
    assert git_atelier.briques_touchees(branche) == ["mail"]
    git_atelier.jeter_chantier(branche)


def test_rebuild_simule_par_defaut():
    res = rebuild.rebuild_brique("mail", reel=False)
    assert res["reel"] is False and res["ok"] is True
    assert res["commande"].startswith("docker compose")
    assert "mail" in res["commande"]
