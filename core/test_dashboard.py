"""Tests du dashboard du Cœur — onglet « Créations » (Hub des briques créatives).

Le Hub Créations a migré d'Oria vers le Cœur : le dashboard sert désormais le Studio
(brique 6060) et l'atelier Personnages (5900) en iframe. On vérifie que l'onglet existe
et que les URLs des briques sont bien INJECTÉES au service (placeholders remplacés).
"""

import os

# Secrets requis AVANT l'import du Cœur (main importe le coffre, la Gateway, etc.).
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from routers import dashboard as dashboard_router  # noqa: E402  (S114 : routes déplacées)
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_dashboard_repond():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_hub_atelier_present():
    """Le Hub des créations a fusionné dans l'onglet « Atelier » (tuiles Usine/Forge/…)."""
    html = client.get("/dashboard").text
    assert 'data-vue="atelier"' in html
    assert 'id="vue-atelier"' in html


def test_atelier_dev_est_une_tuile_de_l_atelier():
    """« Atelier dev » n'a plus d'onglet propre : c'est une tuile du hub Atelier
    (switchVue('dev')), sa vue reste servie."""
    html = client.get("/dashboard").text
    assert 'data-vue="dev"' not in html              # plus d'onglet de premier niveau
    assert "switchVue('dev')" in html                # accessible via une tuile de l'Atelier
    assert 'id="vue-dev"' in html                    # la vue IDE existe toujours


def test_bulles_d_aide_presentes():
    """Des bulles d'aide en clair (composant .aide) expliquent chaque section au
    visiteur non technique : au moins sur les onglets et les titres de vues."""
    html = client.get("/dashboard").text
    # Le composant bulle + au moins une explication non technique repère.
    assert 'class="aide"' in html
    assert "aide-txt" in html
    assert "comme à un téléphone" in html          # explication du registre de briques
    assert "standard téléphonique" in html         # explication de la Gateway
    # Info-bulles natives au survol des onglets.
    assert "Parle à ton assistant en langage normal" in html


def test_gateway_hors_onglets_accessible_par_le_registre():
    """La Gateway n'a plus d'onglet : on l'ouvre via sa carte (rubrique Frontend du
    registre, vue_dashboard=gateway). La vue console reste servie."""
    html = client.get("/dashboard").text
    assert 'data-vue="gateway"' not in html          # plus d'onglet de premier niveau
    assert 'id="vue-gateway"' in html                # la console LiteLLM existe toujours


def test_urls_briques_injectees():
    """Les placeholders __STUDIO_UI_URL__ / __PERSONNAGES_UI_URL__ doivent être remplacés."""
    html = client.get("/dashboard").text
    assert "__STUDIO_UI_URL__" not in html
    assert "__PERSONNAGES_UI_URL__" not in html


# ── S128 — URLs d'iframe relatives à l'hôte de la requête (LAN + mesh) ─────────────
def test_urls_iframe_suivent_l_hote_lan(monkeypatch):
    """En LAN (Host = l'IP du HP), les iframes pointent sur CETTE IP, même port, en http.
    Le port du dashboard (:5100) est retiré ; on rebranche sur le port de chaque brique."""
    monkeypatch.delenv("STUDIO_UI_URL", raising=False)
    html = client.get("/dashboard", headers={"host": "192.168.1.89:5100"}).text
    assert "http://192.168.1.89:6060/atelier" in html      # Studio
    assert "http://192.168.1.89:5900/atelier" in html      # Personnages
    assert "http://192.168.1.89:6010/" in html             # Restaurant


def test_urls_iframe_suivent_le_mesh_https(monkeypatch):
    """Depuis un pair du mesh (Host = IP mesh) derrière Caddy (X-Forwarded-Proto=https),
    les iframes passent en HTTPS sur la MÊME IP mesh → plus de mixed content."""
    monkeypatch.delenv("VOIX_UI_URL", raising=False)
    html = client.get("/dashboard", headers={
        "host": "100.124.248.226",
        "x-forwarded-proto": "https",
    }).text
    assert "https://100.124.248.226:6060/atelier" in html  # Studio
    assert "https://100.124.248.226:5985/" in html         # Voix (WebSocket)
    assert "http://100.124.248.226" not in html            # aucune iframe en clair


def test_urls_iframe_localhost_dev(monkeypatch):
    """En dev local (Host = localhost:5100), on retrouve le comportement historique."""
    monkeypatch.delenv("STUDIO_UI_URL", raising=False)
    html = client.get("/dashboard", headers={"host": "localhost:5100"}).text
    assert "http://localhost:6060/atelier" in html
    assert "http://localhost:5900/atelier" in html


def test_url_studio_surchargeable_par_env(monkeypatch):
    """Une surcharge env `<NOM>_UI_URL` (déploiement particulier / SSO) prime sur la
    construction relative à l'hôte."""
    monkeypatch.setenv("STUDIO_UI_URL", "https://studio.exemple.test/atelier")
    monkeypatch.setattr(dashboard_router, "STUDIO_KEY", "")
    html = client.get("/dashboard", headers={"host": "192.168.1.89:5100"}).text
    assert "https://studio.exemple.test/atelier" in html


def test_cle_studio_injectee_dans_iframe(monkeypatch):
    """Avec un compte Studio (STUDIO_KEY), l'iframe transporte la clé en ?api_key=."""
    monkeypatch.delenv("STUDIO_UI_URL", raising=False)
    monkeypatch.setattr(dashboard_router, "STUDIO_KEY", "cle-de-service-123")
    html = client.get("/dashboard", headers={"host": "localhost:5100"}).text
    assert "http://localhost:6060/atelier?api_key=cle-de-service-123" in html


def test_sans_cle_pas_dapi_key(monkeypatch):
    """Sans compte Studio, l'URL de l'iframe reste nue (aucune fuite ?api_key=)."""
    monkeypatch.delenv("STUDIO_UI_URL", raising=False)
    monkeypatch.setattr(dashboard_router, "STUDIO_KEY", "")
    html = client.get("/dashboard", headers={"host": "localhost:5100"}).text
    assert "api_key=" not in html


# ── S102 — Manipulation directe : menu contextuel du dashboard ────────────────────
def test_socle_manipulation_directe_servi():
    """Le Cœur sert le socle (S101/S102) en JavaScript, pour le menu contextuel + modale."""
    r = client.get("/manipulation_directe.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # Le socle expose bien les helpers attendus par le dashboard.
    assert "attacherMenu" in r.text
    assert "function sortable" in r.text


def test_dashboard_charge_le_socle():
    """Le dashboard inclut le socle et n'utilise plus prompt()/confirm() natifs pour
    renommer/supprimer une conversation (remplacés par la modale du socle)."""
    html = client.get("/dashboard").text
    assert '<script src="/manipulation_directe.js"></script>' in html
    # Le menu contextuel est branché sur les conversations et les projets.
    assert "itemsMenuConv" in html
    assert "attacherMenu(el," in html
    # Actions S102 câblées.
    assert "epinglerConversation" in html
    assert "archiverConversation" in html
    assert "rangerConversation" in html
    assert "supprimerProjetParId" in html


def test_dashboard_branche_le_cliquer_deposer_conversations():
    """S104 : le dashboard câble le sortable des conversations (réordonner + glisser sur
    un projet) ; les zones projet portent data-pid et les conversations data-id."""
    html = client.get("/dashboard").text
    assert "brancherDndConversations" in html
    assert "zones: '.asst-projet'" in html
    assert "persistOrdreConversations" in html
    assert "el.dataset.pid = p.id" in html
    assert "el.dataset.id = f.fil" in html
