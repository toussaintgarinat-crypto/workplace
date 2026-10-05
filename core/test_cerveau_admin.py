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

# Routes d'ÉCRITURE volontairement SANS `exiger_admin_cerveau` — chaque entrée dit pourquoi.
# Ajouter une route POST/PUT/PATCH/DELETE au Cœur sans la garder NI l'inscrire ici fait
# échouer `test_toute_route_d_ecriture_est_gardee_ou_listee` (revue S240, I6).
_CHAT = ("appelée sans session par Telegram/Mini App (brique connexion) — même exposition "
         "que /assistant/chat, à fermer avec lui (décision utilisateur à part)")
_DONNEES = ("données de la personne (dashboard), pas le cerveau ; même exposition que "
            "/assistant/chat, à fermer avec lui")
_SESSION = "session obligatoire (exiger_session) : proxy de brique isolé par personne"
LISTE_BLANCHE = {
    ("POST", "/assistant/chat"): _CHAT,
    ("POST", "/mcp"): "clé MCP_KEY propre ; refus si vide avec AUTH_ENABLED=true (mcp.cle_ok)",
    ("POST", "/briefing/executer"): "tâche d'horloge (manifest noyau), appel interne sans session",
    ("POST", "/pouls/battre"): "tâche d'horloge (manifest noyau), appel interne sans session",
    ("POST", "/curateur/cycle"): "tâche d'horloge `curation-hebdo` ; PROPOSE seulement, n'applique rien",
    ("POST", "/sauvegarde-usb/lancer"): "session OU NOYAU_KEY (capacité de l'assistant) ; n'expose aucun secret",
    ("POST", "/sauvegarde-usb/restaurer"): "session OU NOYAU_KEY (capacité de l'assistant) ; n'expose aucun secret",
    ("POST", "/admin/inviter-proche"): "session obligatoire (exiger_session), S181",
    ("POST", "/usine/livrer"): _DONNEES,
    ("DELETE", "/usine/livraisons/{livraison_id}"): _DONNEES,
    ("POST", "/usine/livraisons/{livraison_id}/decrocher"): _DONNEES,
    ("POST", "/usine/livraisons/{livraison_id}/reprendre"): _DONNEES,
    ("POST", "/assistant/conversations/reordonner"): _DONNEES,
    ("PATCH", "/assistant/conversations/{fil:path}"): _DONNEES,
    ("DELETE", "/assistant/conversations/{fil:path}"): _DONNEES,
    ("POST", "/assistant/projets"): _DONNEES,
    ("PATCH", "/assistant/projets/{projet_id}"): _DONNEES,
    ("DELETE", "/assistant/projets/{projet_id}"): _DONNEES,
    ("POST", "/assistant/document"): _DONNEES,
    ("POST", "/assistant/rappels/check"): _DONNEES,
    ("POST", "/assistant/rappels/{rappel_id}/vu"): _DONNEES,
    # Profil d'amorçage : il entre dans le prompt système, donc touche au cerveau —
    # candidat à la garde, laissé hors périmètre S240 (signalé dans le rapport).
    ("POST", "/profil"): _DONNEES,
    ("PATCH", "/profil/identite"): _DONNEES,
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


def test_toute_route_d_ecriture_est_gardee_ou_listee():
    ecriture = _routes_d_ecriture()
    non_couvertes = ecriture - ROUTES_GARDEES - set(LISTE_BLANCHE)
    assert not non_couvertes, f"route(s) d'écriture ni gardée(s) ni listée(s) : {sorted(non_couvertes)}"
    assert not (ROUTES_GARDEES & set(LISTE_BLANCHE)), "une route ne peut être à la fois gardée et listée"
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


def test_session_valide_sans_liste_blanche_autorisee(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    r = client.post("/assistant/persona", json={"persona": "default"}, cookies=_cookie("marina"))
    assert r.status_code == 200, r.text


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


def test_auth_desactivee_sans_liste_blanche_comportement_historique():
    assert auth.AUTH_ENABLED is False
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 200


def test_auth_desactivee_avec_liste_blanche_refuse(monkeypatch):
    """Identité factice « anonymous » + liste blanche posée = configuration incohérente : on
    ferme plutôt que de laisser croire que la liste blanche protège quelque chose."""
    monkeypatch.setenv("CERVEAU_ADMINS", "toussaint")
    r = client.post("/assistant/persona", json={"persona": "default"})
    assert r.status_code == 403
    assert "AUTH_ENABLED" in r.json()["detail"]


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


def test_origin_listee_dans_cors_origins_acceptee(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.exemple.net")
    r = client.post("/assistant/persona", json={"persona": "default"},
                    headers={"Origin": "https://app.exemple.net"})
    assert r.status_code == 200


def test_corps_non_json_refuse_415():
    """Un <form> tiers ne peut envoyer que text/plain, urlencoded ou multipart."""
    for ctype in ("text/plain", "application/x-www-form-urlencoded"):
        r = client.post("/assistant/persona", content=b'{"persona":"default"}',
                        headers={"Content-Type": ctype})
        assert r.status_code == 415, ctype


def test_post_sans_corps_reste_accepte_si_route_sans_corps():
    """Garde sans effet sur une route gardée qui ne prend pas de corps (ex. DELETE)."""
    r = client.delete("/assistant/config/utilisateur")
    assert r.status_code != 415
