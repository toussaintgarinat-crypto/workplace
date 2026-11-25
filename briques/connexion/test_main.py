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


# ═══ S245 : approbation Telegram (routes /approbation/*, drapeau approbateur) ════════
import re

import correspondance as K
import pont

ID_AP = "b2" * 16


class _TgFaux:
    """Adaptateur Telegram configuré qui enregistre boutons et éditions."""
    def __init__(self, casse=()):
        self.boutons, self.editions, self.casse = [], [], set(casse)

    def configure(self):
        return True

    async def envoyer_boutons(self, id_externe, texte, boutons):
        if id_externe in self.casse:
            raise RuntimeError("destinataire KO")
        self.boutons.append((id_externe, texte, boutons))
        return {"chat_id": id_externe, "message_id": 100 + len(self.boutons)}

    async def editer_message(self, chat_id, message_id, texte):
        if chat_id in self.casse:
            raise RuntimeError("KO")
        self.editions.append((chat_id, message_id, texte))


_H = {"X-API-Key": "k1"}


def _approb(ident):
    K.lier("telegram", ident, "u-ok@wp")
    K.definir_approbateur("telegram", ident, True)


@pytest.fixture
def tg(monkeypatch):
    """Telegram factice + aucun approbateur résiduel d'un test précédent."""
    for e in K.lister():
        if e.get("reseau") == "telegram":
            K.delier("telegram", e["id_externe"])
    faux = _TgFaux()
    monkeypatch.setitem(adaptateurs.REGISTRE, "telegram", faux)
    monkeypatch.setattr(main, "API_KEYS", {"k1"})      # les routes /approbation/* sont fail closed
    return faux


def _notif(**kw):
    corps = {"id": ID_AP, "utilisateur": "u-ok@wp", "resume": "Supprimer le client Dupont",
             "sensibilite": "reversible", "prerequis_ok": True, "relance": False,
             "expire_a": 0}
    corps.update(kw)
    return corps


def test_notifier_envoie_a_chaque_approbateur_avec_boutons(tg):
    _approb("n1")
    _approb("n2")
    K.lier("telegram", "n3", "u-ok@wp")            # lié non approbateur : ne reçoit rien
    r = client.post("/approbation/notifier", json=_notif(), headers=_H)
    assert r.status_code == 200
    assert sorted(m["chat_id"] for m in r.json()["messages"]) == ["n1", "n2"]
    assert all("message_id" in m for m in r.json()["messages"])
    assert sorted(b[0] for b in tg.boutons) == ["n1", "n2"]
    kb = tg.boutons[0][2]
    assert [b["callback_data"] for b in kb[0]] == [f"ap:{ID_AP}:ok", f"ap:{ID_AP}:ko"]
    assert "Dupont" in tg.boutons[0][1]


def test_notifier_sans_approbateur_n_envoie_rien(tg):
    K.lier("telegram", "n-lie", "simple@wp")
    r = client.post("/approbation/notifier", json=_notif(), headers=_H)
    assert r.status_code == 200 and r.json() == {"messages": []}
    assert tg.boutons == []


def test_notifier_prerequis_non_reunis_sans_bouton_approuver(tg):
    _approb("n4")
    client.post("/approbation/notifier", json=_notif(prerequis_ok=False), headers=_H)
    _, texte, clavier = tg.boutons[0]
    assert "en attente de preuves" in texte
    assert clavier == []
    assert "ap:" not in str(tg.boutons)


def test_notifier_destructif_dit_que_le_code_est_dans_l_app(tg):
    _approb("n5")
    client.post("/approbation/notifier", json=_notif(sensibilite="destructif"), headers=_H)
    texte = tg.boutons[0][1]
    assert "app" in texte.lower() and "6 chiffres" in texte
    assert not re.search(r"\d{6}", texte)


def test_notifier_relance_est_marque(tg):
    _approb("n6")
    client.post("/approbation/notifier", json=_notif(relance=True), headers=_H)
    assert "Rappel" in tg.boutons[0][1]


def test_notifier_un_destinataire_ko_ne_bloque_pas_les_autres(monkeypatch, tg):
    tg.casse = {"n7"}
    _approb("n7")
    _approb("n8")
    r = client.post("/approbation/notifier", json=_notif(), headers=_H)
    assert [m["chat_id"] for m in r.json()["messages"]] == ["n8"]


def test_notifier_exige_la_cle_api(monkeypatch, tg):
    _approb("n9")
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    assert client.post("/approbation/notifier", json=_notif()).status_code == 401
    assert client.post("/approbation/notifier", json=_notif(),
                       headers={"X-API-Key": "mauvaise"}).status_code == 401
    assert tg.boutons == []
    r = client.post("/approbation/notifier", json=_notif(), headers={"X-API-Key": "k1"})
    assert r.status_code == 200 and len(r.json()["messages"]) == 1


def test_notifier_et_mettre_a_jour_fermes_si_api_keys_vide(monkeypatch, tg):
    """Sans API_KEYS la route serait ouverte : n'importe qui ferait écrire le bot aux
    approbateurs avec un texte arbitraire. Fail closed."""
    _approb("n10")
    monkeypatch.setattr(main, "API_KEYS", set())
    assert client.post("/approbation/notifier", json=_notif()).status_code == 403
    r = client.post("/approbation/mettre_a_jour",
                    json={"messages": [{"chat_id": "n10", "message_id": 1}], "texte": "x"})
    assert r.status_code == 403
    assert tg.boutons == [] and tg.editions == []


def test_mettre_a_jour_edite_chaque_message(monkeypatch, tg):
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    r = client.post("/approbation/mettre_a_jour", headers={"X-API-Key": "k1"}, json={
        "messages": [{"chat_id": "m1", "message_id": 5}, {"chat_id": "m2", "message_id": 6}],
        "texte": "✅ Approuvée"})
    assert r.status_code == 200 and r.json() == {"edites": 2}
    assert tg.editions == [("m1", 5, "✅ Approuvée"), ("m2", 6, "✅ Approuvée")]


def test_mettre_a_jour_exige_la_cle_api(monkeypatch, tg):
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    r = client.post("/approbation/mettre_a_jour",
                    json={"messages": [{"chat_id": "m1", "message_id": 5}], "texte": "x"})
    assert r.status_code == 401 and tg.editions == []


def test_routes_approbation_ne_sont_pas_proxifiees(monkeypatch, tg):
    """Le catch-all /{chemin:path} relaie au dashboard : les routes doivent le précéder."""
    monkeypatch.setattr(main.miniapp, "verifier_session", lambda *_: pytest.fail("proxy"))
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    h = {"X-API-Key": "k1"}
    assert client.post("/approbation/notifier", json=_notif(), headers=h).status_code == 200
    assert client.post("/approbation/mettre_a_jour", headers=h,
                       json={"messages": [], "texte": "x"}).status_code == 200
    assert client.post("/correspondances/approbateur", headers=h, json={
        "reseau": "telegram", "id_externe": "inexistant", "approbateur": True}
    ).status_code == 404


# ── webhook ──────────────────────────────────────────────────────────────────────────
def test_webhook_callback_query_est_route_vers_traiter_callback(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3")
    vus = []

    async def faux_cb(reseau, cb):
        vus.append((reseau, cb.from_id, cb.data))
        return {"ok": True, "raison": "ok"}

    async def pas_traiter(*a, **k):
        raise AssertionError("un clic ne doit pas passer par traiter()")

    monkeypatch.setattr(pont, "traiter_callback", faux_cb)
    monkeypatch.setattr(pont, "traiter", pas_traiter)
    upd = {"update_id": 1, "callback_query": {
        "id": "c", "from": {"id": 42}, "data": f"ap:{ID_AP}:ok",
        "message": {"message_id": 3, "chat": {"id": 42, "type": "private"}}}}
    r = client.post("/webhook/telegram", json=upd,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "s3"})
    assert r.status_code == 200 and r.json() == {"ok": True}      # corps constant
    assert vus == [("telegram", "42", f"ap:{ID_AP}:ok")]


def test_webhook_callback_exige_toujours_la_signature(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3")
    vus = []

    async def faux_cb(reseau, cb):
        vus.append(cb)
        return {"ok": True}

    monkeypatch.setattr(pont, "traiter_callback", faux_cb)
    upd = {"callback_query": {"id": "c", "from": {"id": 42}, "data": "x",
                              "message": {"message_id": 3, "chat": {"id": 42,
                                                                     "type": "private"}}}}
    assert client.post("/webhook/telegram", json=upd).status_code == 401
    assert vus == []


# ── pose du drapeau approbateur ─────────────────────────────────────────────────────
def test_liaison_ordinaire_ne_peut_pas_poser_approbateur():
    r = client.post("/correspondances", json={
        "reseau": "telegram", "id_externe": "lb1", "utilisateur": "u@wp", "approbateur": True})
    assert r.status_code == 200
    assert K.est_approbateur("telegram", "lb1") is False
    assert not K.table()["telegram:lb1"].get("approbateur")


def test_liaison_ordinaire_ne_retire_ni_n_accorde_le_droit():
    _approb("lb2")
    client.post("/correspondances", json={"reseau": "telegram", "id_externe": "lb2",
                                          "utilisateur": "u-ok@wp"})
    assert K.est_approbateur("telegram", "lb2") is True          # même compte : conservé
    client.post("/correspondances", json={"reseau": "telegram", "id_externe": "lb2",
                                          "utilisateur": "autre@wp"})
    assert K.est_approbateur("telegram", "lb2") is False         # autre compte : retiré


def test_route_approbateur_pose_et_retire_le_drapeau(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    h = {"X-API-Key": "k1"}
    K.lier("telegram", "pa1", "u@wp")
    r = client.post("/correspondances/approbateur", headers=h, json={
        "reseau": "telegram", "id_externe": "pa1", "approbateur": True})
    assert r.status_code == 200 and r.json()["approbateur"] is True
    assert K.est_approbateur("telegram", "pa1") is True
    r = client.post("/correspondances/approbateur", headers=h, json={
        "reseau": "telegram", "id_externe": "pa1", "approbateur": False})
    assert r.status_code == 200 and K.est_approbateur("telegram", "pa1") is False


def test_route_approbateur_fermee_si_api_keys_vide(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", set())
    K.lier("telegram", "pa2", "u@wp")
    r = client.post("/correspondances/approbateur", json={
        "reseau": "telegram", "id_externe": "pa2", "approbateur": True})
    assert r.status_code == 403
    assert K.est_approbateur("telegram", "pa2") is False


def test_route_approbateur_exige_la_cle(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    K.lier("telegram", "pa3", "u@wp")
    r = client.post("/correspondances/approbateur", json={
        "reseau": "telegram", "id_externe": "pa3", "approbateur": True})
    assert r.status_code == 401 and K.est_approbateur("telegram", "pa3") is False


def test_route_approbateur_refuse_entree_inconnue_ou_non_liee(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"k1"})
    h = {"X-API-Key": "k1"}
    assert client.post("/correspondances/approbateur", headers=h, json={
        "reseau": "telegram", "id_externe": "n-existe-pas", "approbateur": True}
    ).status_code == 404
    K.resoudre("telegram", "pa4", "Attente")
    assert client.post("/correspondances/approbateur", headers=h, json={
        "reseau": "telegram", "id_externe": "pa4", "approbateur": True}).status_code == 404
    assert K.est_approbateur("telegram", "pa4") is False


# ── S245 : webhook sans secret = source non authentifiée (fail closed) ────────────────
_UPD_CB = {"update_id": 1, "callback_query": {
    "id": "c", "from": {"id": 42}, "data": f"ap:{ID_AP}:ok",
    "message": {"message_id": 3, "chat": {"id": 42, "type": "private"}}}}


def test_webhook_callback_sans_secret_est_refuse_sans_toucher_le_coeur(monkeypatch):
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    vus = []

    async def faux_cb(reseau, cb):
        vus.append(cb)
        return {"ok": True, "raison": "ok"}

    async def pas_traiter(*a, **k):
        raise AssertionError("un clic ne doit pas passer par traiter()")

    monkeypatch.setattr(pont, "traiter_callback", faux_cb)
    monkeypatch.setattr(pont, "traiter", pas_traiter)
    for nom in ("decider_approbation", "armer_code", "soumettre_code"):
        monkeypatch.setattr(main.client_assistant, nom,
                            lambda *a, **k: pytest.fail("Cœur appelé"))
    r = client.post("/webhook/telegram", json=_UPD_CB)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert vus == []


def test_webhook_callback_corps_constant_meme_si_ignore(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3")

    async def faux_cb(reseau, cb):
        return {"ok": False, "raison": "ignore"}

    monkeypatch.setattr(pont, "traiter_callback", faux_cb)
    r = client.post("/webhook/telegram", json=_UPD_CB,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "s3"})
    assert r.json() == {"ok": True}


@pytest.mark.parametrize("secret,entete,attendu", [(None, {}, False),
                                                   ("s3", {"X-Telegram-Bot-Api-Secret-Token": "s3"}, True)])
def test_webhook_message_transmet_le_drapeau_source_authentifiee(monkeypatch, secret, entete,
                                                                 attendu):
    if secret:
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
    else:
        monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    vus = []

    async def faux_traiter(reseau, e, **k):
        vus.append(k.get("source_authentifiee"))
        return {"ok": True}

    monkeypatch.setattr(pont, "traiter", faux_traiter)
    upd = {"message": {"chat": {"id": 555}, "text": "coucou", "from": {"first_name": "T"}}}
    r = client.post("/webhook/telegram", json=upd, headers=entete)
    assert r.status_code == 200 and r.json()["recus"] == 1
    assert vus == [attendu]


def test_notifier_refuse_un_id_non_hex32(tg):
    for mauvais in ("abc", "Z" * 32, "A1" * 16, "a1" * 17, ""):
        r = client.post("/approbation/notifier", json=_notif(id=mauvais), headers=_H)
        assert r.status_code == 422, mauvais
    assert tg.boutons == []


def test_notifier_ne_cible_que_les_approbateurs_du_demandeur(tg):
    K.lier("telegram", "na", "alice")
    K.definir_approbateur("telegram", "na", True)
    K.lier("telegram", "nb", "bob")
    K.definir_approbateur("telegram", "nb", True)
    r = client.post("/approbation/notifier", json=_notif(utilisateur="alice"), headers=_H)
    assert [m["chat_id"] for m in r.json()["messages"]] == ["na"]
    assert [b[0] for b in tg.boutons] == ["na"]


def test_notifier_exige_l_utilisateur(tg):
    corps = _notif()
    corps.pop("utilisateur")
    assert client.post("/approbation/notifier", json=corps, headers=_H).status_code == 422
