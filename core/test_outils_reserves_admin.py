"""Outils réservés à l'admin du cerveau (revue S240, C-B).

Le chat répond SANS session (Telegram, Mini App) : sans ce verrou, « écris ce fichier »,
« exécute ce script », « fusionne ce chantier », « restaure la sauvegarde » ou « active cet
addendum de prompt » s'exécutaient pour n'importe quel appareil du LAN/mesh — via la brique
dev, qui monte le dépôt en écriture et le socket Docker.

Règle : `outils.executer` (point de passage UNIQUE du chat, du co-agent et de /mcp) refuse
un outil réservé si le contexte ne porte pas `droits.ADMIN_CERVEAU` — posé par
/assistant/chat seulement quand la requête a une session admin du cerveau (même règle que
`exiger_admin_cerveau`, anti-CSRF compris). /mcp et le co-agent autonome n'en ont jamais.

$ cd core && python3 -m pytest test_outils_reserves_admin.py -v
"""
import asyncio
import json
import os
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402

import auth  # noqa: E402
import droits  # noqa: E402
import outils  # noqa: E402
from etat import registre  # noqa: E402
from starlette.requests import Request  # noqa: E402


def _fake_request(cookies: dict) -> Request:
    entete = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return Request({"type": "http", "method": "POST", "path": "/assistant/chat",
                    "headers": [(b"cookie", entete.encode())] if cookies else []})

RESERVES = ["dev_ide_ecrire_fichier", "dev_ide_executer", "dev_ide_lire_fichier", "dev_demander",
            "dev_fusionner", "dev_lancer", "dev_plan_valider", "dev_jeter", "dev_skill_creer",
            "sauvegarde_usb_restaurer", "sauvegarde_usb_lancer",
            "amelioration_decider", "capacite_decider", "curateur_lancer"]


@pytest.mark.parametrize("nom", RESERVES)
def test_liste_des_reserves(nom):
    assert droits.est_reserve_admin(nom)


@pytest.mark.parametrize("nom", ["heure", "agenda_lister", "mail_lister", "dev_chantiers_x_inexistant_mais_dev"])
def test_les_autres_outils_ne_sont_pas_reserves(nom):
    attendu = nom.startswith("dev_")  # toute la brique dev est réservée (lecture du dépôt = .env)
    assert droits.est_reserve_admin(nom) is attendu


def test_refus_sans_admin_sans_appel_reseau(monkeypatch):
    appels = []

    async def faux(nom, args, reg):
        appels.append(nom)
        return "exécuté"
    monkeypatch.setattr(outils, "_executer", faux)
    r = asyncio.run(outils.executer("dev_ide_executer", {"chemin": "x.py"}, registre))
    assert appels == []
    assert json.loads(r)["ok"] is False and "admin" in json.loads(r)["erreur"]


def test_execution_avec_admin(monkeypatch):
    async def faux(nom, args, reg):
        return "exécuté"
    monkeypatch.setattr(outils, "_executer", faux)

    async def tour():
        jeton = droits.ADMIN_CERVEAU.set(True)
        try:
            return await outils.executer("dev_ide_executer", {}, registre)
        finally:
            droits.ADMIN_CERVEAU.reset(jeton)
    assert asyncio.run(tour()) == "exécuté"


def test_outil_ordinaire_sans_admin_inchange(monkeypatch):
    async def faux(nom, args, reg):
        return "ok"
    monkeypatch.setattr(outils, "_executer", faux)
    assert asyncio.run(outils.executer("heure", {}, registre)) == "ok"


# ── Qui est admin pour un tour de chat ───────────────────────────────────────

def test_chat_sans_session_quand_auth_activee_pas_admin(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    assert asyncio.run(auth.admin_cerveau_ou_none(_fake_request({}))) is None


def test_chat_avec_session_admin(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    auth._cache_access_token["toussaint"] = ("at", time.time() + 60)
    auth._cache_access_token["marina"] = ("at", time.time() + 60)
    try:
        ok = _fake_request({auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": "toussaint", "refresh_token": "r"})})
        ko = _fake_request({auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": "marina", "refresh_token": "r"})})
        assert asyncio.run(auth.admin_cerveau_ou_none(ok))["sub"] == "toussaint"
        assert asyncio.run(auth.admin_cerveau_ou_none(ko)) is None
    finally:
        auth._cache_access_token.clear()


def test_route_chat_pose_le_droit_pour_le_tour(monkeypatch):
    """/assistant/chat transmet le droit au flux SSE (contexte copié après la route)."""
    from fastapi.testclient import TestClient
    import assistant
    import main
    vus = []

    async def faux_converser(messages, reg, **kw):
        vus.append(droits.ADMIN_CERVEAU.get())
        yield {"type": "texte", "contenu": "ok"}
        yield {"type": "fin"}
    monkeypatch.setattr(assistant, "converser", faux_converser)
    c = TestClient(main.app)
    # 1) dev local avec opt-in explicite (conftest) : admin.
    c.post("/assistant/chat", json={"messages": [{"role": "user", "content": "x"}]})
    # 2) sans opt-in ni auth : fermé par défaut (revue S240, I3).
    monkeypatch.delenv("CERVEAU_OUVERT_SANS_AUTH", raising=False)
    c.post("/assistant/chat", json={"messages": [{"role": "user", "content": "y"}]})
    # 3) HP : auth active, CERVEAU_ADMINS posé, sans cookie (Telegram) : non.
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    c.post("/assistant/chat", json={"messages": [{"role": "user", "content": "z"}]})
    assert vus == [True, False, False]


def test_mcp_jamais_admin(monkeypatch):
    import mcp

    async def faux(nom, args, reg):
        return "exécuté"
    monkeypatch.setattr(outils, "_executer", faux)
    rep = asyncio.run(mcp.traiter({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "sauvegarde_usb_restaurer", "arguments": {}}},
                                  registre))
    assert "exécuté" not in json.dumps(rep)


# ── Revue S240, M3 : réservation aussi par BRIQUE et par drapeau de manifest ─────

def _registre_reel():
    from registre import Registre
    r = Registre()
    r.charger()
    return r


def test_toutes_les_capacites_de_la_brique_dev_sont_reservees():
    reg = _registre_reel()
    manifeste = json.load(open(os.path.join(os.path.dirname(__file__), "..", "briques", "dev", "manifest.json")))
    noms = [c["nom"] for c in manifeste.get("capacites") or []]
    assert noms
    for nom in noms:
        assert outils.est_reserve_admin(nom, reg), nom


def test_capacites_noyau_sensibles_reservees_par_drapeau():
    reg = _registre_reel()
    manifeste = json.load(open(os.path.join(os.path.dirname(__file__), "..", "briques", "noyau", "manifest.json")))
    drapees = {c["nom"] for c in manifeste["capacites"] if c.get("reserve_admin")}
    assert {"sauvegarde_usb_lancer", "sauvegarde_usb_restaurer"} <= drapees
    for nom in drapees:
        assert outils.est_reserve_admin(nom, reg), nom


def test_capacite_dev_au_nom_quelconque_reservee_par_sa_brique(monkeypatch):
    """Une future capacité de la brique dev qui ne commencerait pas par `dev_`."""
    monkeypatch.setattr(outils, "_capacites_dynamiques",
                        lambda reg: {"executer_script": {"brique": "dev"},
                                     "lire_meteo": {"brique": "geo"},
                                     "purger_tout": {"brique": "x", "reserve_admin": True}})
    assert outils.est_reserve_admin("executer_script", object())
    assert outils.est_reserve_admin("purger_tout", object())
    assert not outils.est_reserve_admin("lire_meteo", object())

    async def faux(nom, args, reg):
        return "exécuté"
    monkeypatch.setattr(outils, "_executer", faux)
    r = asyncio.run(outils.executer("executer_script", {}, object()))
    assert json.loads(r)["ok"] is False
