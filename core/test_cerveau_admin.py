"""Garde des routes qui MODIFIENT le cerveau (S240, T1).

Avant S240, `assistant.router` n'était monté qu'avec `lire_contexte_tenant` (non bloquant) :
n'importe quel appareil du LAN/mesh pouvait poser une clé fournisseur ou changer le modèle
sans session. Ces tests verrouillent :
- la LISTE exacte des routes gardées (contrat : une route de modification ajoutée plus tard
  sans garde fait échouer `test_routes_gardees_exactement`) ;
- le comportement de `exiger_admin_cerveau` (401 sans session, 403 hors `CERVEAU_ADMINS`,
  cohérence avec `AUTH_ENABLED=false`).

$ cd core && python3 -m pytest test_cerveau_admin.py -v
"""
import os
import tempfile
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import session_registre  # noqa: E402

client = TestClient(main.app)

# (méthode, chemin) des routes qui modifient le cerveau — rien de plus, rien de moins.
ROUTES_GARDEES = {
    ("POST", "/assistant/config"),
    ("PUT", "/assistant/config/organisation"),
    ("DELETE", "/assistant/config/organisation"),
    ("PUT", "/assistant/config/utilisateur"),
    ("DELETE", "/assistant/config/utilisateur"),
    ("POST", "/assistant/muscle"),
    ("POST", "/assistant/routage"),
    ("POST", "/assistant/persona"),
    ("POST", "/assistant/langue"),
    ("POST", "/assistant/voix"),
    ("POST", "/assistant/cle-openrouter"),
    ("POST", "/assistant/cle-fournisseur"),
    ("POST", "/assistant/modeles"),
    ("DELETE", "/assistant/modeles/{nom:path}"),
    ("POST", "/assistant/forge-modele"),
    ("GET", "/sauvegarde-usb/env"),
    # Revue S240, I7 : auto-amélioration du prompt et curateur (gates humains), rechargement
    # des manifests, déclenchement manuel de l'horloge. Aucun appelant HTTP sans session
    # (le chat appelle `amelioration`/`curateur` en interne, l'horloge tourne dans le
    # processus) ; `make reload` (core/Makefile) ne marche plus qu'avec AUTH_ENABLED=false.
    ("POST", "/amelioration/proposer"),
    ("POST", "/amelioration/{id_}/evaluer"),
    ("POST", "/amelioration/{id_}/valider"),
    ("POST", "/amelioration/{id_}/appliquer"),
    ("POST", "/amelioration/{id_}/rejeter"),
    ("POST", "/amelioration/desactiver"),
    ("POST", "/curateur/capacites/{id_}/retenir"),
    ("POST", "/curateur/capacites/{id_}/rejeter"),
    ("POST", "/briques/reload"),
    ("POST", "/horloge/executer"),
}

# Routes d'écriture sous SESSION (+ anti-CSRF d'origine), sans exiger l'admin (revue S240, I-B) :
# elles nourrissent le prompt système (projets : `instructions` ; profil d'amorçage) ou le RAG
# (document déposé). Seul appelant : le dashboard (vérifié — ni connexion ni Mini App).
ROUTES_SESSION = {
    ("POST", "/assistant/projets"), ("PATCH", "/assistant/projets/{projet_id}"),
    ("DELETE", "/assistant/projets/{projet_id}"), ("POST", "/assistant/document"),
    ("POST", "/profil"), ("PATCH", "/profil/identite"),
}

# Routes d'ÉCRITURE volontairement SANS `exiger_admin_cerveau` — chaque entrée dit pourquoi.
# Ajouter une route POST/PUT/PATCH/DELETE au Cœur sans la garder NI l'inscrire ici fait
# échouer `test_toute_route_d_ecriture_est_gardee_ou_listee` (revue S240, I6).
_CHAT = ("appelée sans session par Telegram/Mini App (brique connexion) — même exposition "
         "que /assistant/chat, à fermer avec lui (décision utilisateur à part)")
_DONNEES = ("données de la personne (conversations, rappels, agenda) — n'entrent pas dans le "
            "prompt système ; même exposition que /assistant/chat, à fermer avec lui")
_USINE = ("pilotage de l'usine (génération d'apps, coût LLM) — même exposition que "
          "/assistant/chat, à fermer avec lui")
_SESSION = "session obligatoire (exiger_session) : proxy de brique isolé par personne"
LISTE_BLANCHE = {
    ("POST", "/assistant/chat"): _CHAT,
    ("POST", "/mcp"): "clé MCP_KEY propre ; refus si vide avec AUTH_ENABLED=true (mcp.cle_ok)",
    ("POST", "/briefing/executer"): "tâche d'horloge (manifest noyau), appel interne sans session",
    ("POST", "/pouls/battre"): "tâche d'horloge (manifest noyau), appel interne sans session",
    ("POST", "/curateur/cycle"): "tâche d'horloge `curation-hebdo` ; PROPOSE seulement, n'applique rien",
    ("POST", "/sauvegarde-usb/lancer"): "NOYAU_KEY (temps constant) OU session admin du cerveau "
        "(exiger_admin_cerveau, anti-CSRF) ; via le chat, outil réservé (droits.py)",
    ("POST", "/sauvegarde-usb/restaurer"): "NOYAU_KEY (temps constant) OU session admin du cerveau "
        "(exiger_admin_cerveau, anti-CSRF) ; via le chat, outil réservé (droits.py)",
    ("POST", "/admin/inviter-proche"): "session obligatoire (exiger_session), S181",
    ("POST", "/usine/livrer"): _USINE,
    ("DELETE", "/usine/livraisons/{livraison_id}"): _USINE,
    ("POST", "/usine/livraisons/{livraison_id}/decrocher"): _USINE,
    ("POST", "/usine/livraisons/{livraison_id}/reprendre"): _USINE,
    ("POST", "/assistant/conversations/reordonner"): _DONNEES,
    ("PATCH", "/assistant/conversations/{fil:path}"): _DONNEES,
    ("DELETE", "/assistant/conversations/{fil:path}"): _DONNEES,
    ("POST", "/assistant/rappels/check"): _DONNEES,
    ("POST", "/assistant/rappels/{rappel_id}/vu"): _DONNEES,
    **{(m, c): _DONNEES for m, c in [
        ("PATCH", "/agenda/evenements/{event_id}/rappels"), ("POST", "/agenda/timetree/connect"),
        ("POST", "/agenda/timetree/select"), ("POST", "/agenda/timetree/sync"),
        ("DELETE", "/agenda/timetree/disconnect"), ("POST", "/agenda/google/sync"),
        ("DELETE", "/agenda/google/disconnect"), ("POST", "/agenda/calendriers"),
        ("POST", "/agenda/calendriers/{calendar_id}/invitations"), ("POST", "/agenda/evenements"),
        ("PATCH", "/agenda/evenements/{event_id}"), ("DELETE", "/agenda/evenements/{event_id}"),
        ("POST", "/agenda/evenements/{event_id}/documents"), ("DELETE", "/agenda/documents/{att_id}"),
        ("POST", "/agenda/evenements/{event_id}/commentaires"),
        ("DELETE", "/agenda/commentaires/{comment_id}"),
        ("POST", "/agenda/calendriers/{calendar_id}/etiquettes"),
        ("PATCH", "/agenda/etiquettes/{label_id}"), ("DELETE", "/agenda/etiquettes/{label_id}")]},
    **{(m, f"/{p}/{{chemin:path}}"): _SESSION
       for p in ("mail-app", "studio-app", "atelier-images-video-app", "atelier-veille-app")
       for m in ("POST", "PUT", "PATCH", "DELETE")},
}


def _routes_avec_garde() -> set[tuple[str, str]]:
    trouvees = set()
    for r in main.app.routes:
        deps = getattr(r, "dependant", None)
        if deps is None:
            continue
        appels = {d.call for d in deps.dependencies}
        if auth.exiger_admin_cerveau in appels:
            for m in r.methods:
                trouvees.add((m, r.path))
    return trouvees


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    """Registre de session neuf + cache de jetons vidé + aucun admin par défaut."""
    ancien = session_registre.DB
    session_registre.DB = os.path.join(tempfile.mkdtemp(), "session_registre.db")
    auth._cache_access_token.clear()
    monkeypatch.delenv("CERVEAU_ADMINS", raising=False)
    try:
        yield
    finally:
        session_registre.DB = ancien
        auth._cache_access_token.clear()


def _cookie(sub: str) -> dict:
    """Cookie de session valide pour `sub`, access token déjà en cache (pas d'appel Keycloak)."""
    auth._cache_access_token[sub] = ("at-cache", time.time() + 60)
    return {auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": sub, "refresh_token": "rt-1"})}


def test_routes_gardees_exactement():
    assert _routes_avec_garde() == ROUTES_GARDEES


def _routes_d_ecriture() -> set[tuple[str, str]]:
    return {(m, r.path) for r in main.app.routes
            for m in (getattr(r, "methods", None) or set()) & {"POST", "PUT", "PATCH", "DELETE"}}


def _routes_avec(dep) -> set[tuple[str, str]]:
    return {(m, r.path) for r in main.app.routes if getattr(r, "dependant", None)
            and dep in {d.call for d in r.dependant.dependencies} for m in r.methods}


def test_routes_session_exactement():
    assert _routes_avec(auth.exiger_session_api) | _routes_avec(auth.exiger_session_api_fichier) \
        == ROUTES_SESSION


def test_routes_session_refusent_sans_session(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    for methode, chemin in sorted(ROUTES_SESSION):
        r = client.request(methode, chemin.replace("{projet_id}", "x"), json={}, follow_redirects=False)
        assert r.status_code == 401, (methode, chemin, r.status_code)


def test_routes_session_n_exigent_pas_l_admin(monkeypatch):
    """Une session hors CERVEAU_ADMINS peut gérer ses projets (pas le cerveau)."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    r = client.post("/assistant/projets", json={"nom": "p"}, cookies=_cookie("marina"))
    assert r.status_code == 200, r.text


def test_routes_session_anti_csrf():
    r = client.post("/assistant/projets", json={"nom": "p"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/profil", content=b'{"contenu":"x"}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_toute_route_d_ecriture_est_gardee_ou_listee():
    ecriture = _routes_d_ecriture()
    non_couvertes = ecriture - ROUTES_GARDEES - ROUTES_SESSION - set(LISTE_BLANCHE)
    assert not non_couvertes, f"route(s) d'écriture ni gardée(s) ni listée(s) : {sorted(non_couvertes)}"
    assert not (ROUTES_GARDEES & set(LISTE_BLANCHE)), "une route ne peut être à la fois gardée et listée"
    assert not (ROUTES_SESSION & (ROUTES_GARDEES | set(LISTE_BLANCHE)))
    assert set(LISTE_BLANCHE) <= ecriture, f"entrées obsolètes : {sorted(set(LISTE_BLANCHE) - ecriture)}"


def test_chat_et_lectures_restent_ouverts():
    """Telegram/Mini App/S2S passent par /assistant/chat et /assistant/historique_utilisateur
    sans session Keycloak : ils ne doivent JAMAIS hériter de la garde."""
    gardees = _routes_avec_garde()
    for libre in [("POST", "/assistant/chat"), ("GET", "/assistant/historique_utilisateur"),
                  ("GET", "/assistant/config"), ("GET", "/assistant/muscle")]:
        assert libre not in gardees


def test_sans_session_refuse_401_quand_auth_activee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    for methode, chemin in sorted(ROUTES_GARDEES):
        r = client.request(methode, chemin, json={}, follow_redirects=False)
        assert r.status_code == 401, (methode, chemin, r.status_code)


def test_session_valide_sans_liste_blanche_refusee(monkeypatch):
    """Revue S240, I3 — fermé par défaut : auth active mais CERVEAU_ADMINS vide = personne
    n'est admin du cerveau (une session quelconque ne suffit pas)."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 403
    assert "CERVEAU_ADMINS" in r.json()["detail"]


def test_opt_in_dev_ignore_quand_auth_activee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_OUVERT_SANS_AUTH", "1")
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 403


def test_session_hors_liste_blanche_refusee_403(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint, autre")
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 403


def test_session_dans_liste_blanche_autorisee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "autre,toussaint")
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("toussaint"))
    assert r.status_code == 200, r.text


def test_auth_desactivee_sans_opt_in_fermee(monkeypatch):
    """Revue S240, I3 : sans auth ni opt-in explicite, le cerveau est fermé."""
    assert auth.AUTH_ENABLED is False
    monkeypatch.delenv("CERVEAU_OUVERT_SANS_AUTH", raising=False)
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 403
    assert "CERVEAU_OUVERT_SANS_AUTH" in r.json()["detail"]


def test_auth_desactivee_avec_opt_in_dev_ouverte(monkeypatch):
    """Dev local (pas de Keycloak) : opt-in explicite CERVEAU_OUVERT_SANS_AUTH=1."""
    monkeypatch.setenv("CERVEAU_OUVERT_SANS_AUTH", "1")
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 200


def test_auth_desactivee_avec_liste_blanche_refuse(monkeypatch):
    """Identité factice « anonymous » + liste blanche posée = configuration incohérente : on
    ferme plutôt que de laisser croire que la liste blanche protège quelque chose."""
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 403
    assert "AUTH_ENABLED" in r.json()["detail"]


def test_avertissement_au_demarrage_si_ferme(monkeypatch, caplog):
    import logging
    monkeypatch.delenv("CERVEAU_OUVERT_SANS_AUTH", raising=False)
    with caplog.at_level(logging.WARNING):
        auth.avertir_si_cerveau_ferme()
    assert "cerveau" in caplog.text.lower() and "CERVEAU_ADMINS" in caplog.text
    caplog.clear()
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    with caplog.at_level(logging.WARNING):
        auth.avertir_si_cerveau_ferme()
    assert caplog.text == ""


# ── Anti-CSRF (revue S240, I1) ───────────────────────────────────────────────
# Une page tierce ouverte dans le navigateur d'un admin connecté ne doit pas pouvoir
# déclencher une écriture du cerveau avec son cookie.

def test_sec_fetch_site_autre_que_same_origin_refuse():
    for valeur in ("cross-site", "same-site", "none"):
        r = client.post("/assistant/persona", json={"persona": "default"},
                        headers={"Sec-Fetch-Site": valeur})
        assert r.status_code == 403, valeur


def test_sec_fetch_site_same_origin_accepte():
    r = client.post("/assistant/persona", json={"persona": "default"},
                    headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_origin_etrangere_refusee():
    for origine in ("https://evil.example", "null", "http://testserver.evil.example"):
        r = client.post("/assistant/persona", json={"persona": "default"},
                        headers={"Origin": origine})
        assert r.status_code == 403, origine


def test_origin_du_coeur_ou_localhost_acceptee():
    # TestClient envoie Host: testserver → l'origine du Cœur lui-même est acceptée, quel que
    # soit le schéma (Caddy termine le TLS devant le Cœur : Origin https, requête http).
    for origine in ("http://testserver", "https://testserver", "http://localhost:5100",
                    "http://127.0.0.1:5100"):
        r = client.post("/assistant/persona", json={"persona": "default"},
                        headers={"Origin": origine})
        assert r.status_code == 200, origine


def test_cors_origins_n_autorise_aucune_origine_tierce(monkeypatch):
    """Revue S240, M1 : `CORS_ORIGINS` n'ouvre PAS l'écriture du cerveau à une autre origine."""
    monkeypatch.setenv("CORS_ORIGINS", "https://app.exemple.net")
    r = client.post("/assistant/persona", json={"persona": "default"},
                    headers={"Origin": "https://app.exemple.net"})
    assert r.status_code == 403


def test_corps_non_json_refuse_415():
    """Un <form> tiers ne peut envoyer que text/plain, urlencoded ou multipart."""
    for ctype in ("text/plain", "application/x-www-form-urlencoded"):
        r = client.post("/assistant/persona", content=b'{"persona":"default"}',
                        headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype


def test_post_sans_corps_reste_accepte_si_route_sans_corps(monkeypatch):
    """Garde sans effet sur une route gardée qui ne prend pas de corps (ex. DELETE) : la
    route s'exécute et répond 200 (revue S240, M2 : statut exact, brique données simulée)."""
    import config_tenant
    appels = []

    async def faux_supprimer(org_id, utilisateur, client=None):
        appels.append((org_id, utilisateur))
    monkeypatch.setattr(config_tenant, "supprimer_couche_utilisateur", faux_supprimer)
    r = client.delete("/assistant/config/utilisateur")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(appels) == 1
