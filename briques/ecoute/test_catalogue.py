"""Tests du catalogue gratuit (S43) — pur, hors ligne."""
import catalogue


def test_quatre_noms_honnetes():
    # On expose les 4 modèles RÉELLEMENT embarqués (pas de bourrage à « 5-6 »).
    assert len(catalogue.CATALOGUE_GRATUIT) == 4
    modeles = {n["modele"] for n in catalogue.CATALOGUE_GRATUIT}
    assert modeles == {"hey_jarvis_v0.1", "alexa_v0.1", "hey_mycroft_v0.1", "hey_rhasspy_v0.1"}


def test_un_seul_defaut_hey_jarvis():
    defauts = [n for n in catalogue.CATALOGUE_GRATUIT if n.get("defaut")]
    assert len(defauts) == 1
    assert catalogue.nom_defaut() == "hey_jarvis_v0.1"


def test_est_gratuit():
    assert catalogue.est_gratuit("alexa_v0.1")
    assert not catalogue.est_gratuit("acme_corp")  # un nom sur mesure n'est pas gratuit


def test_trouver():
    assert catalogue.trouver("alexa_v0.1")["label"] == "Alexa"
    assert catalogue.trouver("inconnu") is None
