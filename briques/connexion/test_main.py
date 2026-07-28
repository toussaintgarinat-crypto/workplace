"""Tests API (TestClient) : santé, webhooks, sondage, administration des correspondances."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import adaptateurs
import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert set(data["reseaux"]) == {"telegram", "whatsapp", "discord", "email_sms", "webpush"}
    assert data["configures"] == []                    # aucun token en test
    assert data["mode_ouvert"] is False


def test_webhook_reseau_inconnu():
    assert client.post("/webhook/nawak", json={}).status_code == 404


def test_webhook_discord_ping_pong():
    # PING Discord (type 1) sans signature → la vérification refuse d'abord (401).
    r = client.post("/webhook/discord", json={"type": 1})
    assert r.status_code == 401


def test_webhook_telegram_inconnu_non_relaye():
    # Pas de token → verif webhook ne réclame rien ; l'interlocuteur n'étant pas relié,
    # rien n'est envoyé à l'assistant (aucun réseau réel touché).
    upd = {"message": {"chat": {"id": 555}, "text": "coucou", "from": {"first_name": "T"}}}
    r = client.post("/webhook/telegram", json=upd)
    assert r.status_code == 200
    data = r.json()
    assert data["recus"] == 1 and data["autorises"] == 0


def test_correspondances_lier_et_lister():
    # voir l'interlocuteur (en attente) via un sondage est inutile ; on lie directement
    r = client.post("/correspondances",
                    json={"reseau": "telegram", "id_externe": "777", "utilisateur": "p@wp"})
    assert r.status_code == 200 and r.json()["ok"] is True
    liste = client.get("/correspondances").json()["correspondances"]
    assert any(c["id_externe"] == "777" and c["statut"] == "lie" for c in liste)


def test_correspondances_lier_invalide():
    assert client.post("/correspondances", json={"utilisateur": "x"}).status_code == 422


def test_sonder_non_configure():
    r = client.post("/sonder/telegram")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "reseau": "telegram", "traites": 0, "configure": False}


def test_envoyer_non_configure():
    r = client.post("/envoyer", json={"reseau": "telegram", "id_externe": "1", "texte": "hi"})
    assert r.status_code == 409


# ── S210 : la capacité `connexion_envoyer` telle que l'assistant l'appelle ─────────
# Elle était MORTE depuis son écriture : le manifeste annonçait `destinataire`/`message`,
# le modèle `Envoi` exige `reseau`/`id_externe`/`texte` → 422 à chaque envoi. Ce test
# construit le corps À PARTIR DU MANIFESTE (pas d'une constante recopiée) et vérifie que
# le message atteint réellement l'adaptateur du réseau.
def _params_capacite(nom):
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
    cap = next(c for c in manifest["capacites"] if c["nom"] == nom)
    return cap["params"]


class _FauxReseau:
    """Adaptateur configuré qui note ce qu'on lui demande d'envoyer (rien ne part)."""
    def __init__(self):
        self.envoyes = []

    def configure(self):
        return True

    async def envoyer(self, id_externe, texte):
        self.envoyes.append((id_externe, texte))
        return True


def test_connexion_envoyer_delivre_avec_les_params_du_manifeste(monkeypatch):
    faux = _FauxReseau()
    monkeypatch.setitem(adaptateurs.REGISTRE, "telegram", faux)

    params = _params_capacite("connexion_envoyer")
    valeurs = {"reseau": "telegram", "id_externe": "424242", "texte": "Le pont fonctionne."}
    assert set(params) == set(valeurs), (
        f"Le manifeste déclare {sorted(params)} — ce test ne prouverait pas l'appel réel.")

    r = client.post("/envoyer", json={nom: valeurs[nom] for nom in params})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert faux.envoyes == [("424242", "Le pont fonctionne.")]


@pytest.mark.parametrize("params", [_params_capacite("connexion_envoyer")])
def test_manifeste_declare_tous_les_champs_requis_par_envoi(params):
    """Filet local du contrat (le filet du parc est `tests/test_contrat_capacites.py`)."""
    requis = {nom for nom, champ in main.Envoi.model_fields.items() if champ.is_required()}
    assert requis <= set(params), f"champs requis non déclarés : {sorted(requis - set(params))}"
