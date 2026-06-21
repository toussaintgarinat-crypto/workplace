"""S89 — task trace : la narration FR pas-à-pas, on/off + traduction des outils + flux SSE.

On prouve : trace ON → journal pas-à-pas NON vide et EN FRANÇAIS ; trace OFF → journal vide
(l'agent bosse en silence) ; la traduction des outils d'un agent en phrases FR ; et que le flux
SSE rejoue bien la narration."""
import os

import traceur
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


# ── Module pur ───────────────────────────────────────────────────────────────────
def test_phrase_pour_outil_en_francais():
    assert "lis le fichier" in traceur.phrase_pour_outil("Read", {"file_path": "x.py"}).lower()
    assert "modifie" in traceur.phrase_pour_outil("Edit", {"file_path": "x.py"}).lower()
    assert "commande" in traceur.phrase_pour_outil("Bash", {"command": "pytest -q"}).lower()
    assert "outil Inconnu" in traceur.phrase_pour_outil("Inconnu", {})


def test_phrase_pour_evenement_pretooluse():
    p = traceur.phrase_pour_evenement(
        {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "a.py"}})
    assert "écris le fichier a.py" in p.lower()
    # PostToolUse → ignoré (on narre l'intention, pas l'écho)
    assert traceur.phrase_pour_evenement({"hook_event_name": "PostToolUse"}) == ""


def test_traceur_ecrit_et_relit():
    f = os.path.join(os.environ["DEV_TRACES"], "unitaire.jsonl")
    t = traceur.Traceur(f)
    t.effacer()
    t.noter("J'ouvre la branche.")
    t.noter("Je commite.")
    assert t.phrases() == ["J'ouvre la branche.", "Je commite."]
    t.effacer()
    assert t.phrases() == []


# ── Bout en bout via l'API ────────────────────────────────────────────────────────
def test_trace_on_narre_en_francais():
    r = client.post("/chantiers", json={"intention": "ajouter un champ", "brique_cible": "mail",
                                        "agent": "factice", "trace": True})
    cid = r.json()["id"]
    assert r.json()["trace_active"] is True

    r = client.post(f"/chantiers/{cid}/lancer")
    ch = r.json()
    # Journal archivé NON vide, en français, pas-à-pas.
    assert len(ch["journal"]) >= 3
    assert any("commite" in p.lower() for p in ch["journal"])
    assert any("briques/mail/" in p for p in ch["journal"])

    # Le flux SSE rejoue la narration (suivre=false = archive puis clôture).
    r = client.get(f"/chantiers/{cid}/trace?suivre=false")
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "data:" in r.text and "simule honnêtement" in r.text

    client.delete(f"/chantiers/{cid}")


def test_trace_off_silence():
    r = client.post("/chantiers", json={"intention": "discret", "agent": "factice", "trace": False})
    cid = r.json()["id"]
    r = client.post(f"/chantiers/{cid}/lancer")
    assert r.json()["journal"] == []  # l'agent a bossé en silence
    # SSE sans aucune phrase narrée, juste l'évènement de clôture.
    r = client.get(f"/chantiers/{cid}/trace?suivre=false")
    assert "phrase" not in r.text  # aucune étape racontée
    client.delete(f"/chantiers/{cid}")


def test_jeter_efface_la_trace():
    r = client.post("/chantiers", json={"intention": "ephemere", "agent": "factice", "trace": True})
    cid = r.json()["id"]
    client.post(f"/chantiers/{cid}/lancer")
    assert traceur.lire(traceur.fichier_pour(cid))  # trace présente
    client.delete(f"/chantiers/{cid}")
    assert traceur.lire(traceur.fichier_pour(cid)) == []  # disparue avec le chantier
