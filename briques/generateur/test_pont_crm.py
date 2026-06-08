"""Preuve offline du pont consenti app→CRM (S24) — brique donnees + forge mockées.

On monte un `httpx.MockTransport` qui simule :
  • la brique **donnees** (`GET /apps/{app_id}/export`) → la source des enregistrements ;
  • la brique **forge** (`POST /crm`, `DELETE /crm/{id}`) → le CRM du cabinet.

On vérifie le comportement de `pont_crm` :

  1. **consentement = Oui** (liste blanche) → seules les entités choisies remontent,
     un lead créé par enregistrement, provenance tracée ;
  2. **idempotence** → un 2ᵉ `pousser()` ne recrée rien (registre) ;
  3. **consentement = Non** → RIEN ne sort (souveraineté), aucun POST /crm ;
  4. **révocation sans purge** → pont arrêté, données CONSERVÉES côté CRM ;
  5. **révocation avec purge** → les leads remontés sont supprimés du CRM (DELETE) ;
  6. **Forge injoignable** → best-effort, aucune exception, erreurs comptées.

Registre isolé dans une base temporaire (pas la vraie /data/apps.db).
Lancer : `python3 test_pont_crm.py`.
"""
import json
import os
import tempfile

import httpx


# ── Faux backend (brique donnees + brique forge) ─────────────────────────────────

def make_transport(state):
    """MockTransport routant donnees (export) + forge (crm) et journalisant les appels."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        state["calls"].append(f"{method} {path}")

        # Forge injoignable simulé (panne réseau).
        if state.get("forge_ko") and "/crm" in path:
            raise httpx.ConnectError("forge down")

        # donnees : export des enregistrements de l'app.
        if method == "GET" and path.endswith("/export"):
            return httpx.Response(200, json={"app_id": "app-1", "entites": state["entites"]})

        # forge : créer un prospect.
        if method == "POST" and path.endswith("/crm"):
            body = json.loads(request.content)
            lead_id = f"lead-{len(state['leads']) + 1}"
            state["leads"][lead_id] = body
            return httpx.Response(200, json={"ok": True, "id": lead_id, **body})

        # forge : supprimer un prospect.
        if method == "DELETE" and "/crm/" in path:
            lead_id = path.rsplit("/", 1)[-1]
            state["leads"].pop(lead_id, None)
            state["supprimes"].append(lead_id)
            return httpx.Response(200, json={"ok": True})

        return httpx.Response(404, json={"path": path})

    return httpx.MockTransport(handler)


def patch(pc, state):
    """Remplace httpx.Client de pont_crm par un client au transport mocké."""
    transport = make_transport(state)
    orig = httpx.Client

    def fake_client(*a, **k):
        k.pop("timeout", None)
        return orig(transport=transport)

    pc.httpx.Client = fake_client
    return orig


# ── Scénarios ───────────────────────────────────────────────────────────────────

def run():
    # Registre isolé : base temporaire dédiée au test.
    tmp = tempfile.mkdtemp()
    os.environ["DB_PATH"] = os.path.join(tmp, "apps_test.db")
    import importlib
    import pont_crm as pc
    importlib.reload(pc)  # relit DB_PATH + recrée la table dans la base temporaire

    orig_client = httpx.Client
    ok = 0

    # Source commune : 2 entités, seule "clients" est en liste blanche.
    entites = {
        "clients": [
            {"_id": "r1", "nom": "Jean Dupont", "email": "jean@exemple.fr", "telephone": "0102"},
            {"_id": "r2", "societe": "ACME", "mail": "contact@acme.fr"},
        ],
        "factures": [
            {"_id": "f1", "montant": 1200},
        ],
    }

    # 1) Consentement = Oui, liste blanche ["clients"] → 2 leads, factures ignorées.
    st = {"entites": entites, "leads": {}, "supprimes": [], "calls": []}
    patch(pc, st)
    r = pc.pousser("app-1", {"actif": True, "entites": ["clients"]})
    pc.httpx.Client = orig_client
    assert r["actif"] and r["pousses"] == 2 and r["erreurs"] == 0, r
    assert len(st["leads"]) == 2, st["leads"]
    # repli du nom sur la société, mapping mail→email, provenance tracée
    noms = {l["nom"] for l in st["leads"].values()}
    assert "Jean Dupont" in noms and "ACME" in noms, noms
    assert all("[pont:app-1/clients]" in l["notes"] for l in st["leads"].values()), st["leads"]
    print("✅ 1. consentement Oui : seules les entités en liste blanche remontent (2 leads, provenance tracée)")
    ok += 1

    # 2) Idempotence : un 2ᵉ pousser ne recrée rien.
    st2 = {"entites": entites, "leads": {}, "supprimes": [], "calls": []}
    patch(pc, st2)
    r = pc.pousser("app-1", {"actif": True, "entites": ["clients"]})
    pc.httpx.Client = orig_client
    assert r["pousses"] == 0 and r["ignores"] == 2, r
    assert len(st2["leads"]) == 0, "aucun nouveau POST /crm attendu"
    print("✅ 2. idempotence : 2ᵉ remontée → 0 créé, 2 ignorés (registre)")
    ok += 1

    # 3) Consentement = Non → rien ne sort.
    st3 = {"entites": entites, "leads": {}, "supprimes": [], "calls": []}
    patch(pc, st3)
    r = pc.pousser("app-2", {"actif": False, "entites": ["clients"]})
    pc.httpx.Client = orig_client
    assert not r["actif"] and r["pousses"] == 0, r
    assert st3["calls"] == [], "aucun appel réseau quand le partage est désactivé"
    print("✅ 3. consentement Non : RIEN ne sort, aucun appel réseau (souveraineté)")
    ok += 1

    # 4) Révocation SANS purge → pont arrêté, données conservées.
    st4 = {"entites": entites, "leads": {}, "supprimes": [], "calls": []}
    patch(pc, st4)
    r = pc.revoquer("app-1", purger=False)
    pc.httpx.Client = orig_client
    assert not r["purge"] and r["supprimes"] == 0 and r["restants"] == 2, r
    assert st4["supprimes"] == [], "aucun DELETE quand on ne purge pas"
    print("✅ 4. révocation sans purge : pont arrêté, 2 prospects conservés côté CRM")
    ok += 1

    # 5) Révocation AVEC purge → les leads remontés sont supprimés du CRM.
    st5 = {"entites": entites, "leads": {}, "supprimes": [], "calls": []}
    patch(pc, st5)
    r = pc.revoquer("app-1", purger=True)
    pc.httpx.Client = orig_client
    assert r["purge"] and r["supprimes"] == 2 and r["restants"] == 0, r
    assert len(st5["supprimes"]) == 2, st5["supprimes"]
    print("✅ 5. révocation avec purge : 2 prospects supprimés du CRM (DELETE), registre vidé")
    ok += 1

    # 6) Forge injoignable → best-effort, aucune exception, erreurs comptées.
    st6 = {"entites": entites, "leads": {}, "supprimes": [], "calls": [], "forge_ko": True}
    patch(pc, st6)
    r = pc.pousser("app-3", {"actif": True, "entites": ["clients"]})
    pc.httpx.Client = orig_client
    assert r["actif"] and r["pousses"] == 0 and r["erreurs"] == 2, r
    print("✅ 6. Forge injoignable : best-effort, 0 remonté, 2 erreurs, aucune exception")
    ok += 1

    print(f"\n{ok}/6 scénarios OK")


if __name__ == "__main__":
    run()
