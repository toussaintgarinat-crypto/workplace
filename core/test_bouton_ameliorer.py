"""Tests S132 — bouton [🛠️ Améliorer] + suggestions dev_*."""
import os
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main
import suggestions
from fastapi.testclient import TestClient

client = TestClient(main.app)

def test_bouton_ameliorer_present_dans_dashboard():
    html = client.get("/dashboard").text
    assert 'id="btn-ameliorer"' in html
    assert "🛠️" in html
    assert "Améliorer" in html

def test_bouton_ameliorer_injecte_le_bon_message():
    html = client.get("/dashboard").text
    assert "Je veux améliorer la solution." in html
    assert "taperAction" in html

def test_suggestions_dev_demander_avec_confirmation():
    s = suggestions.pour_resultat("dev_demander", {}, '{"confirmation_requise": true}', confirmation=True)
    labels = [b["label"] for b in s]
    assert any("Valider" in l for l in labels)
    assert any("Annuler" in l for l in labels)
    envois = [b["envoi"] for b in s]
    assert any("confirme" in e.lower() for e in envois)

def test_suggestions_dev_plan_valider_avec_confirmation():
    s = suggestions.pour_resultat("dev_plan_valider", {"cid": "abc"}, '{"confirmation_requise": true}', confirmation=True)
    labels = [b["label"] for b in s]
    assert any("plan" in l.lower() or "coder" in l.lower() or "Valider" in l for l in labels)
    assert len(s) >= 2

def test_suggestions_dev_lancer_sans_confirmation():
    s = suggestions.pour_resultat("dev_lancer", {"cid": "abc"}, '{"statut": "revue"}', confirmation=False)
    labels = [b["label"] for b in s]
    assert any("Fusionner" in l or "prod" in l.lower() for l in labels)
    assert any("diff" in l.lower() or "Diff" in l for l in labels)
    assert len(s) >= 2

def test_suggestions_dev_fusionner_avec_confirmation():
    s = suggestions.pour_resultat("dev_fusionner", {"cid": "abc"}, '{"confirmation_requise": true}', confirmation=True)
    labels = [b["label"] for b in s]
    assert any("Fusionner" in l or "prod" in l.lower() for l in labels)
    assert any("diff" in l.lower() or "Diff" in l for l in labels)
    assert any("Annuler" in l for l in labels)

def test_suggestions_outil_generique_inchange():
    s = suggestions.pour_resultat("agenda_creer_evenement", {}, '{"confirmation_requise": true}', confirmation=True)
    labels = [b["label"] for b in s]
    assert "✅ Confirmer" in labels
    assert "✖ Annuler" in labels

def test_suggestions_sans_confirmation_vide():
    s = suggestions.pour_resultat("lister_entreprises", {}, '{"entreprises": []}', confirmation=False)
    assert s == []
