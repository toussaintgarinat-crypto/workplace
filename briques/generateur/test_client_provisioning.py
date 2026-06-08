"""Preuve offline du compte client auto (S23) — Keycloak admin + Oria mockés.

On monte un `httpx.MockTransport` qui simule l'API admin Keycloak (recherche/création
d'utilisateur, execute-actions-email) et l'endpoint Oria `/rejoindre`, puis on vérifie
le comportement de `client_provisioning.creer_compte_client` :

  1. nouveau client       → compte créé + email d'accès envoyé + rattaché à l'espace ;
  2. client déjà présent  → idempotent (réutilisé), email renvoyé, rattaché ;
  3. email invalide/absent→ onboarding ignoré proprement (aucun appel réseau) ;
  4. Keycloak injoignable → best-effort : statut d'échec clair, AUCUNE exception ;
  5. envoi d'email KO     → compte quand même créé, email_envoye=False (best-effort).

Lancer : `python3 test_client_provisioning.py` (pytest optionnel, asserts purs).
"""
import json

import httpx

import client_provisioning as cp


# ── Faux backend (Keycloak admin + Oria) ────────────────────────────────────────

def make_transport(state):
    """Retourne un MockTransport qui route Keycloak admin + Oria et journalise les appels."""
    users = state["users"]  # email -> id

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        state["calls"].append(f"{method} {path}")

        # Keycloak : recherche d'utilisateur par email
        if method == "GET" and path.endswith("/users"):
            email = request.url.params.get("email")
            uid = users.get(email)
            return httpx.Response(200, json=[{"id": uid, "email": email}] if uid else [])

        # Keycloak : création d'utilisateur
        if method == "POST" and path.endswith("/users"):
            body = json.loads(request.content)
            uid = f"kc-{len(users) + 1}"
            users[body["email"]] = uid
            base = str(request.url).split("?")[0]
            return httpx.Response(201, headers={"Location": f"{base}/{uid}"})

        # Keycloak : envoi de l'email « définis ton mot de passe »
        if method == "PUT" and path.endswith("/execute-actions-email"):
            if state.get("email_ko"):
                return httpx.Response(500, json={"error": "smtp down"})
            state["email_envoye_appel"] = True
            return httpx.Response(204)

        # Oria : rattachement à l'espace
        if method == "POST" and "/rejoindre" in path:
            state["rejoindre_appel"] = request.url.params.get("user_id")
            return httpx.Response(200, json={"status": "ok"})

        return httpx.Response(404, json={"path": path})

    return httpx.MockTransport(handler)


def patch(monkeypatch_state):
    """Remplace httpx.Client (transport mocké) + op._token (pas de vrai Keycloak)."""
    transport = make_transport(monkeypatch_state)
    orig_client = httpx.Client

    def fake_client(*a, **k):
        k.pop("timeout", None)
        return orig_client(transport=transport, headers=k.get("headers"))

    cp.httpx.Client = fake_client
    if monkeypatch_state.get("token_ko"):
        cp.op._token = lambda: (_ for _ in ()).throw(RuntimeError("keycloak injoignable"))
    else:
        cp.op._token = lambda: "fake-token"


def restore(orig_client, orig_token):
    cp.httpx.Client = orig_client
    cp.op._token = orig_token


# ── Scénarios ───────────────────────────────────────────────────────────────────

def run():
    orig_client, orig_token = httpx.Client, cp.op._token
    ok = 0

    # 1) Nouveau client : créé + email + rattaché
    st = {"users": {}, "calls": []}
    patch(st)
    r = cp.creer_compte_client("client@exemple.fr", "Jean Dupont", "world-1", "ACME")
    restore(orig_client, orig_token)
    assert r["ok"] and r["compte_cree"] and r["email_envoye"] and r["rattache_espace"], r
    assert st["rejoindre_appel"] == r["user_id"], st
    assert any("POST" in c and c.endswith("/users") for c in st["calls"]), st["calls"]
    print("✅ 1. nouveau client : compte créé + email envoyé + rattaché à l'espace")
    ok += 1

    # 2) Client déjà présent : idempotent (pas de POST /users), email renvoyé
    st = {"users": {"client@exemple.fr": "kc-existant"}, "calls": []}
    patch(st)
    r = cp.creer_compte_client("client@exemple.fr", "Jean Dupont", "world-1", "ACME")
    restore(orig_client, orig_token)
    assert r["ok"] and not r["compte_cree"] and r["email_envoye"], r
    assert r["user_id"] == "kc-existant", r
    assert not any(c == "POST /admin/realms/oria/users" for c in st["calls"]), st["calls"]
    print("✅ 2. client déjà présent : réutilisé (idempotent), email renvoyé")
    ok += 1

    # 3) Email invalide → ignoré, aucun appel réseau
    st = {"users": {}, "calls": []}
    patch(st)
    r = cp.creer_compte_client("", "Jean", "world-1")
    restore(orig_client, orig_token)
    assert not r["ok"] and not st["calls"], (r, st["calls"])
    print("✅ 3. email absent/invalide : onboarding ignoré, aucun appel réseau")
    ok += 1

    # 4) Keycloak injoignable → best-effort, pas d'exception
    st = {"users": {}, "calls": [], "token_ko": True}
    patch(st)
    r = cp.creer_compte_client("client@exemple.fr", "Jean", "world-1")
    restore(orig_client, orig_token)
    assert not r["ok"] and "Keycloak" in r["message"], r
    print("✅ 4. Keycloak injoignable : échec best-effort, aucune exception levée")
    ok += 1

    # 5) Envoi d'email KO → compte quand même créé, email_envoye=False
    st = {"users": {}, "calls": [], "email_ko": True}
    patch(st)
    r = cp.creer_compte_client("client@exemple.fr", "Jean", "world-1")
    restore(orig_client, orig_token)
    assert r["ok"] and r["compte_cree"] and not r["email_envoye"], r
    assert r["rattache_espace"], r  # le rattachement reste tenté
    print("✅ 5. SMTP KO : compte créé, email_envoye=False, rattachement quand même tenté")
    ok += 1

    print(f"\n{ok}/5 scénarios OK")


if __name__ == "__main__":
    run()
