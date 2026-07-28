"""Tests de sortie du S211 : la brique n'est plus ni ouverte ni un proxy interne.

Trois preuves, dans l'ordre du sprint :
  • une URL visant une adresse non publique est refusée — **y compris via redirection** ;
  • un appel sans clé est rejeté dès que `API_KEYS` est posé ;
  • une réponse trop grosse est coupée, sans être chargée en mémoire d'abord.

Aucun test ne touche le réseau : la résolution DNS est remplacée par une table connue
(`dns`) et les réponses HTTP par respx. C'est volontaire — un test de sécurité qui dépend
d'Internet devient un test qui rougit pour de mauvaises raisons.
"""

import importlib

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import reseau

# Adresses publiques pour les faux DNS. PAS les blocs de documentation RFC 5737
# (192.0.2/24, 198.51.100/24, 203.0.113/24) : Python les classe `is_private` → la garde les
# refuse, et le test mesurerait le contraire de ce qu'il croit. Aucun paquet ne part vers
# ces adresses (respx intercepte tout).
IP_PUBLIQUE = "93.184.216.34"
IP_PUBLIQUE_2 = "104.18.32.7"


@pytest.fixture
def dns(monkeypatch):
    """Remplace la résolution DNS par une table explicite : `table[nom] = [ip, ...]`."""
    table: dict[str, list[str]] = {}

    async def _faux_resoudre(hote: str, port: int) -> list[str]:
        if hote not in table:
            raise OSError(f"nom inconnu dans le test : {hote}")
        return table[hote]

    monkeypatch.setattr(reseau, "_resoudre", _faux_resoudre)
    return table


@pytest.fixture
def client(tmp_path, monkeypatch):
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client_ferme(tmp_path, monkeypatch):
    """La brique fermée — `main.API_KEYS` étant lu à l'import, il faut recharger le module."""
    import main
    import stockage
    monkeypatch.setenv("INGESTION_API_KEYS", "cle-de-test")
    importlib.reload(main)
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    with TestClient(main.app) as c:
        yield c
    # Rendre la brique à son mode ouvert pour les autres modules de test : le rechargement
    # doit se faire APRÈS avoir retiré la variable, sinon la clé survit au test.
    monkeypatch.delenv("INGESTION_API_KEYS", raising=False)
    importlib.reload(main)


# ── SSRF : cibles directes ───────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5100/interne",          # loopback
    "http://10.0.0.5/admin",                  # privé RFC 1918
    "http://192.168.1.89:5200/documents",     # le HP lui-même
    "http://169.254.169.254/latest/meta-data",  # métadonnées cloud (lien-local)
    "http://[::1]:8080/",                     # loopback IPv6
])
def test_ingerer_url_refuse_une_adresse_non_publique(client, url):
    resp = client.post("/ingerer/url", json={"url": url})
    assert resp.status_code == 403, resp.text
    assert "refus" in resp.json()["detail"].lower()


def test_ingerer_url_refuse_un_nom_dhote_docker_interne(client, dns):
    """`http://gateway:5100` : nom valide, résolution privée → refusé sur l'IP, pas sur le nom."""
    dns["gateway"] = ["172.18.0.7"]
    resp = client.post("/ingerer/url", json={"url": "http://gateway:5100/v1/models"})
    assert resp.status_code == 403
    assert "172.18.0.7" in resp.json()["detail"]


def test_ingerer_url_refuse_un_nom_resolvant_en_public_ET_en_prive(client, dns):
    """Une seule adresse interne suffit à refuser : on ne parie pas sur l'ordre du resolver."""
    dns["piege.test"] = [IP_PUBLIQUE, "127.0.0.1"]
    resp = client.post("/ingerer/url", json={"url": "http://piege.test/doc"})
    assert resp.status_code == 403


# ── SSRF : le contournement par redirection ──────────────────────────────────

@respx.mock
def test_ingerer_url_refuse_une_redirection_vers_la_loopback(client, dns):
    """Le cœur du sprint : la première cible est publique, la seconde ne l'est pas."""
    dns["exemple.test"] = [IP_PUBLIQUE]
    depart = respx.get("http://exemple.test/doc").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1:5100/secret"}))
    interne = respx.get("http://127.0.0.1:5100/secret").mock(
        return_value=httpx.Response(200, text="SECRET INTERNE"))

    resp = client.post("/ingerer/url", json={"url": "http://exemple.test/doc"})

    assert resp.status_code == 403, resp.text
    assert depart.called
    assert not interne.called, "la redirection interne a été suivie — la garde ne sert à rien"


@respx.mock
def test_ingerer_url_refuse_une_redirection_relative_vers_un_hote_interne(client, dns):
    """Location relative au protocole (`//interne/…`) : le nom d'hôte change quand même."""
    dns["exemple.test"] = [IP_PUBLIQUE]
    dns["interne"] = ["10.1.2.3"]
    respx.get("http://exemple.test/doc").mock(
        return_value=httpx.Response(301, headers={"location": "//interne/secret"}))

    resp = client.post("/ingerer/url", json={"url": "http://exemple.test/doc"})
    assert resp.status_code == 403


@respx.mock
def test_ingerer_url_suit_une_redirection_publique(client, dns):
    """La garde ne doit pas casser le cas normal : une redirection publique passe."""
    dns["exemple.test"] = [IP_PUBLIQUE]
    dns["autre.test"] = [IP_PUBLIQUE_2]
    respx.get("http://exemple.test/doc").mock(
        return_value=httpx.Response(302, headers={"location": "http://autre.test/page.html"}))
    respx.get("http://autre.test/page.html").mock(
        return_value=httpx.Response(200, html="<html><body>Bonjour le monde</body></html>",
                                    headers={"content-type": "text/html"}))

    resp = client.post("/ingerer/url", json={"url": "http://exemple.test/doc"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["nb_caracteres"] > 0
    # Le nom retenu vient de l'URL FINALE, pas de celle demandée.
    assert resp.json()["nom"] == "page.html"


@respx.mock
def test_ingerer_url_abandonne_sur_une_boucle_de_redirections(client, dns):
    dns["boucle.test"] = [IP_PUBLIQUE]
    respx.get("http://boucle.test/a").mock(
        return_value=httpx.Response(302, headers={"location": "http://boucle.test/a"}))

    resp = client.post("/ingerer/url", json={"url": "http://boucle.test/a"})
    assert resp.status_code == 403
    assert "redirection" in resp.json()["detail"].lower()


# ── Plafond de taille ────────────────────────────────────────────────────────

async def _flux(morceaux: int = 5, taille: int = 1000):
    """Corps envoyé en morceaux → réponse SANS content-length, comme un vrai flux."""
    for _ in range(morceaux):
        yield b"A" * taille


@respx.mock
def test_ingerer_url_refuse_une_taille_annoncee_trop_grande(client, dns):
    """Content-Length crédible : on refuse AVANT de lire le corps."""
    dns["gros.test"] = [IP_PUBLIQUE]
    respx.get("http://gros.test/enorme.pdf").mock(return_value=httpx.Response(
        200, content=_flux(), headers={"content-length": str(reseau.TAILLE_MAX + 1)}))

    resp = client.post("/ingerer/url", json={"url": "http://gros.test/enorme.pdf"})
    assert resp.status_code == 413


@respx.mock
def test_ingerer_url_coupe_un_corps_qui_depasse_sans_content_length(client, dns, monkeypatch):
    """Serveur qui ne dit rien (ou qui ment) : le plafond est mesuré pendant la lecture."""
    dns["gros.test"] = [IP_PUBLIQUE]
    monkeypatch.setattr(reseau, "TAILLE_MAX", 1024)
    respx.get("http://gros.test/flux").mock(
        return_value=httpx.Response(200, content=_flux()))

    resp = client.post("/ingerer/url", json={"url": "http://gros.test/flux"})
    assert resp.status_code == 413


# ── Authentification ─────────────────────────────────────────────────────────

def test_appel_sans_cle_est_rejete_quand_API_KEYS_est_pose(client_ferme):
    assert client_ferme.get("/documents").status_code == 401
    assert client_ferme.get("/dossiers").status_code == 401
    assert client_ferme.post("/ingerer/url", json={"url": "http://x.test/a"}).status_code == 401
    assert client_ferme.delete("/documents/nimporte").status_code == 401


def test_appel_avec_mauvaise_cle_est_rejete(client_ferme):
    resp = client_ferme.get("/documents", headers={"X-API-Key": "pas-la-bonne"})
    assert resp.status_code == 401


def test_appel_avec_la_bonne_cle_passe(client_ferme):
    assert client_ferme.get("/documents", headers={"X-API-Key": "cle-de-test"}).status_code == 200
    # Dialecte Bearer accepté aussi (motif transcription/veille-info).
    assert client_ferme.get(
        "/documents", headers={"Authorization": "Bearer cle-de-test"}).status_code == 200


def test_sante_reste_ouverte_pour_le_healthcheck(client_ferme):
    """Le healthcheck du docker-compose n'a aucune clé à présenter : /sante doit rester libre."""
    assert client_ferme.get("/sante").status_code == 200


def test_sans_cle_configuree_la_brique_reste_ouverte(client):
    """Déploiement non configuré : comportement historique inchangé, on ne casse personne."""
    assert client.get("/documents").status_code == 200


def _cles_lues(monkeypatch, **env) -> set[str]:
    """Recharge `main` avec l'environnement donné et rend la liste de clés retenue."""
    import main
    for nom in ("INGESTION_API_KEYS", "API_KEYS"):
        monkeypatch.delenv(nom, raising=False)
    for nom, valeur in env.items():
        monkeypatch.setenv(nom, valeur)
    importlib.reload(main)
    lues = set(main.API_KEYS)
    for nom in ("INGESTION_API_KEYS", "API_KEYS"):
        monkeypatch.delenv(nom, raising=False)
    importlib.reload(main)
    return lues


def test_INGESTION_API_KEYS_prime_sur_la_variable_generique(monkeypatch):
    """`API_KEYS` est partagée par 22 briques via le .env racine : s'appuyer dessus pour
    fermer l'ingestion les basculerait TOUTES en fail-closed d'un coup. La variable dédiée gagne,
    et elle gagne seule — pas d'union avec la générique, sinon fermer l'ingestion rouvrirait
    l'accès à quiconque détient n'importe quelle clé de la flotte."""
    assert _cles_lues(monkeypatch, INGESTION_API_KEYS="a,b", API_KEYS="z") == {"a", "b"}


def test_la_variable_generique_reste_un_repli(monkeypatch):
    """Déploiement fermé de bout en bout (toute la flotte sur API_KEYS) : la convention marche."""
    assert _cles_lues(monkeypatch, API_KEYS="z") == {"z"}


def test_aucune_des_deux_laisse_la_brique_ouverte(monkeypatch):
    assert _cles_lues(monkeypatch) == set()
