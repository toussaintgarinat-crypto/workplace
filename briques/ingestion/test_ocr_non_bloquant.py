"""S212 — une extraction longue ne fait plus tomber le healthcheck.

`ingerer_fichier` est un `async def` qui appelait directement `extraction.extraire_texte`,
du CPU synchrone (PyMuPDF, puis Tesseract page par page à 200 dpi). Pendant l'OCR d'un PDF
scanné, la boucle d'événements était donc **occupée** : la brique ne répondait plus à rien,
`/sante` compris. Le healthcheck du `docker-compose.yml` (timeout 10 s, 3 essais) déclarait
la brique `unhealthy` sur un simple gros document — le travail aboutissait, la plateforme
disait qu'il avait échoué.

**Pourquoi un vrai serveur et pas `TestClient`.** Le test qui compte est celui du sprint :
« le healthcheck reste-t-il vert pendant un OCR long ? ». Avec `TestClient` (ou
`httpx.ASGITransport`), le client vit DANS la boucle qu'on cherche à mesurer : si elle est
gelée, le client l'est aussi, et l'attente devient invisible — le test passerait au vert
sur le code d'avant. On monte donc uvicorn dans un fil, et on interroge `/sante` depuis le
fil du test avec `urllib.request.urlopen`, la commande exacte du healthcheck du compose.
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

import extraction
import reseau

# Durée pendant laquelle l'extraction simulée occupe son thread. Assez longue pour que le
# gel soit sans ambiguïté (le healthcheck tolère 10 s), assez courte pour un test rapide.
DUREE_EXTRACTION = 3.0

# Marge accordée à `/sante` pendant l'extraction. Sans le correctif, la réponse ne peut pas
# arriver avant DUREE_EXTRACTION ; avec, elle arrive en millisecondes.
DELAI_SANTE_MAX = 1.0


@pytest.fixture
def base_url(tmp_path, monkeypatch):
    """Un vrai uvicorn sur un port libre, dans un fil — `lifespan` coupé, DB jetable."""
    import stockage
    monkeypatch.setattr(stockage, "DB_CHEMIN", tmp_path / "ingestion.db")
    stockage.initialiser()          # le lifespan ne tournera pas, on le fait à la main

    from main import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))     # port 0 = le noyau en choisit un libre…
    port = sock.getsockname()[1]    # …et on le passe TEL QUEL à uvicorn : aucune course.

    serveur = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    fil = threading.Thread(target=lambda: serveur.run(sockets=[sock]), daemon=True)
    fil.start()

    debut = time.monotonic()
    while not serveur.started and time.monotonic() - debut < 10:
        time.sleep(0.02)
    assert serveur.started, "uvicorn n'a pas démarré"

    yield f"http://127.0.0.1:{port}"

    serveur.should_exit = True
    fil.join(timeout=10)


def test_le_healthcheck_reste_vert_pendant_une_extraction_longue(base_url, monkeypatch):
    """Le test de sortie du sprint : un OCR de plusieurs minutes ne fait pas tomber /sante."""
    import urllib.request

    demarree = threading.Event()
    liberer = threading.Event()

    def extraction_qui_dure(contenu, nom_fichier, type_mime=None):
        demarree.set()
        liberer.wait(DUREE_EXTRACTION + 30)
        return "texte océrisé"

    monkeypatch.setattr(extraction, "extraire_texte", extraction_qui_dure)
    # Le déblocage vient d'un fil INDÉPENDANT : si la boucle était gelée, rien de ce qui
    # tourne dessus ne pourrait relâcher l'extraction, et l'attente serait bien réelle.
    threading.Timer(DUREE_EXTRACTION, liberer.set).start()

    reponse_ingestion = {}

    def ingerer():
        with httpx.Client(base_url=base_url, timeout=60) as c:
            r = c.post("/ingerer", files={"fichier": ("scan.pdf", b"%PDF-1.4 faux scan",
                                                      "application/pdf")})
        reponse_ingestion["statut"] = r.status_code

    fil_ingestion = threading.Thread(target=ingerer)
    fil_ingestion.start()
    assert demarree.wait(10), "l'extraction n'a jamais démarré"

    depart = time.monotonic()
    with urllib.request.urlopen(f"{base_url}/sante", timeout=DUREE_EXTRACTION + 20) as r:
        statut_sante = r.status
    ecoule = time.monotonic() - depart

    assert statut_sante == 200
    assert ecoule < DELAI_SANTE_MAX, (
        f"/sante a mis {ecoule:.1f}s à répondre pendant l'extraction : la boucle "
        f"d'événements est bloquée, le healthcheck (timeout 10 s) tombera sur un gros PDF.")

    liberer.set()
    fil_ingestion.join(timeout=30)
    assert reponse_ingestion.get("statut") == 200, "l'ingestion elle-même doit aboutir"


async def test_ingestion_url_extrait_aussi_hors_boucle(monkeypatch):
    """L'autre chemin d'ingestion : une URL peut pointer sur un PDF scanné, elle aussi."""
    fils: list[str] = []

    def espion(contenu, nom_fichier, type_mime=None):
        fils.append(threading.current_thread().name)
        return "texte"

    async def faux_telecharger(url):
        return b"%PDF-1.4 faux", url, "application/pdf"

    monkeypatch.setattr(extraction, "extraire_texte", espion)
    monkeypatch.setattr(reseau, "telecharger", faux_telecharger)

    await extraction.extraire_depuis_url("http://exemple.test/scan.pdf")

    assert fils, "l'extraction n'a pas été appelée"
    assert fils[0].startswith("ingestion-extraction"), (
        f"extraction exécutée dans {fils[0]!r} : elle doit passer par le pool dédié, "
        f"pas par la boucle d'événements ni par le threadpool partagé d'AnyIO.")


def test_le_pool_d_extraction_est_borne():
    """Un pool NON borné rendrait le correctif illusoire : 50 OCR = 50 threads sur 6 cœurs."""
    assert extraction._POOL._max_workers == extraction._PARALLELISME
    assert extraction._PARALLELISME >= 1
