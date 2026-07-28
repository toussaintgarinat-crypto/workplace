"""Compte client auto à la livraison (S23) — Keycloak admin + Oria mockés, aucun réseau.

Écrit à l'origine comme script autonome (`def run()`), donc jamais exécuté par le filet.
Converti en tests pytest le 2026-07-28 — les 5 scénarios sont conservés à l'identique.
Le patch de `httpx.Client` et de `op._token` passe par `monkeypatch` : le script restaurait
à la main en fin de scénario, et une assertion rouge laissait le module patché pour la suite.
"""
import json

import httpx
import pytest

import client_provisioning as cp

# La VRAIE classe, figée à l'import : un brancheur créé après un premier branchement
# capturerait sinon le FAUX client précédent (cf. le commentaire jumeau de test_pont_crm.py).
_VRAI_CLIENT = httpx.Client


def _transport(etat):
    """MockTransport routant l'API admin Keycloak + le `/rejoindre` d'Oria, et journalisant."""
    comptes = etat["users"]  # email -> id

    def handler(request: httpx.Request) -> httpx.Response:
        chemin, methode = request.url.path, request.method
        etat["calls"].append(f"{methode} {chemin}")

        if methode == "GET" and chemin.endswith("/users"):       # recherche par email
            email = request.url.params.get("email")
            uid = comptes.get(email)
            return httpx.Response(200, json=[{"id": uid, "email": email}] if uid else [])

        if methode == "POST" and chemin.endswith("/users"):      # création
            corps = json.loads(request.content)
            uid = f"kc-{len(comptes) + 1}"
            comptes[corps["email"]] = uid
            base = str(request.url).split("?")[0]
            return httpx.Response(201, headers={"Location": f"{base}/{uid}"})

        if methode == "PUT" and chemin.endswith("/execute-actions-email"):
            if etat.get("email_ko"):
                return httpx.Response(500, json={"error": "smtp down"})
            etat["email_envoye_appel"] = True
            return httpx.Response(204)

        if methode == "POST" and "/rejoindre" in chemin:         # Oria
            etat["rejoindre_appel"] = request.url.params.get("user_id")
            return httpx.Response(200, json={"status": "ok"})

        return httpx.Response(404, json={"path": chemin})

    return httpx.MockTransport(handler)


@pytest.fixture
def backend(monkeypatch):
    """Fabrique un faux backend et branche `client_provisioning` dessus."""
    def brancher(**options):
        etat = {"users": options.pop("users", {}), "calls": [], **options}
        transport = _transport(etat)

        def faux_client(*a, **k):
            k.pop("timeout", None)
            return _VRAI_CLIENT(transport=transport, headers=k.get("headers"))

        monkeypatch.setattr(cp.httpx, "Client", faux_client)
        if etat.get("token_ko"):
            def jeton_ko():
                raise RuntimeError("keycloak injoignable")
            monkeypatch.setattr(cp.op, "_token", jeton_ko)
        else:
            monkeypatch.setattr(cp.op, "_token", lambda: "fake-token")
        return etat
    return brancher


def test_nouveau_client_compte_cree_email_envoye_et_rattache(backend):
    etat = backend()
    r = cp.creer_compte_client("client@exemple.fr", "Jean Dupont", "world-1", "ACME")
    assert r["ok"] and r["compte_cree"] and r["email_envoye"] and r["rattache_espace"], r
    assert etat["rejoindre_appel"] == r["user_id"], etat
    assert any("POST" in c and c.endswith("/users") for c in etat["calls"]), etat["calls"]


def test_client_deja_present_idempotent_et_email_renvoye(backend):
    etat = backend(users={"client@exemple.fr": "kc-existant"})
    r = cp.creer_compte_client("client@exemple.fr", "Jean Dupont", "world-1", "ACME")
    assert r["ok"] and not r["compte_cree"] and r["email_envoye"], r
    assert r["user_id"] == "kc-existant", r
    assert not any(c == "POST /admin/realms/oria/users" for c in etat["calls"]), etat["calls"]


def test_email_absent_onboarding_ignore_sans_aucun_appel_reseau(backend):
    etat = backend()
    r = cp.creer_compte_client("", "Jean", "world-1")
    assert not r["ok"] and not etat["calls"], (r, etat["calls"])


def test_keycloak_injoignable_echec_best_effort_sans_exception(backend):
    """Best-effort : la livraison ne doit jamais tomber parce que l'onboarding a raté."""
    backend(token_ko=True)
    r = cp.creer_compte_client("client@exemple.fr", "Jean", "world-1")
    assert not r["ok"] and "Keycloak" in r["message"], r


def test_smtp_ko_le_compte_est_quand_meme_cree(backend):
    backend(email_ko=True)
    r = cp.creer_compte_client("client@exemple.fr", "Jean", "world-1")
    assert r["ok"] and r["compte_cree"] and not r["email_envoye"], r
    assert r["rattache_espace"], "le rattachement reste tenté même si l'email a échoué"
