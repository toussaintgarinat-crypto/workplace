"""Intégration RÉELLE avec PyAirbyte (S214) — opt-in, réseau requis.

Sauté par défaut : ces tests installent un vrai connecteur depuis PyPI (venv + réseau,
~1 min au premier passage) et n'ont de sens que dans l'image de la brique, où
`/opt/pyairbyte` existe. Le filet standard reste rapide et hors-ligne.

    docker compose -f briques/connecteurs/docker-compose.yml run --rm --entrypoint "" \
      -e CONNECTEURS_TEST_RESEAU=1 connecteurs \
      sh -c "pip install -q pytest pytest-asyncio && pytest -q test_integration_pyairbyte.py"

────────────────────────────────────────────────────────────────────────────────
Ce que ces tests prouvent, et ce qu'ils NE prouvent PAS.

PROUVÉ : le curseur est capté après une sync, recopié dans SQLite, et REPASSÉ au
connecteur au tour suivant (on lit le fichier `--state` que PyAirbyte fabrique).

PAS PROUVÉ ICI : que le volume transféré DIMINUE. C'est une propriété du CONNECTEUR, pas
de cette brique. Mesuré le 2026-07-28 sur deux connecteurs sans identifiants :
  • `source-faker` : curseur écrit (`loop_offset`) mais ignoré en entrée — un `count`
    porté de 500 à 800 avec un curseur à 500 retransfère 800, pas 300 ;
  • un manifeste déclaratif écrit à la main : l'état arrive bien dans le fichier `--state`
    (vérifié), mais la requête repart de `start_datetime`.
La réduction réelle du delta se constate donc sur un connecteur qui l'implémente
(`source-github` avec un jeton) — à faire LIVE. Voir le doc de sprint : le critère de
sortie de S214 n'est PAS déclaré atteint sur ce point.
"""
import asyncio
import json
import os
from pathlib import Path

import pytest

import pont

pytestmark = pytest.mark.skipif(
    os.getenv("CONNECTEURS_TEST_RESEAU") != "1",
    reason="intégration réelle : CONNECTEURS_TEST_RESEAU=1 (réseau + venv connecteur)")

CONNECTEUR = "source-faker"
CONFIG = {"count": 300, "seed": 42}
FLUX = ["users"]


@pytest.fixture(scope="module")
def racine(tmp_path_factory):
    return str(tmp_path_factory.mktemp("travail"))


def _job(action, racine, **extra):
    return {"action": action, "connecteur": CONNECTEUR, "config": CONFIG, "flux": FLUX,
            "schema": "integration", "racine": racine, **extra}


def _executer(job):
    return asyncio.run(pont.executer(job, timeout=900))


def test_le_pont_est_bien_present_dans_l_image():
    assert pont.disponible(), (
        f"{pont.PYTHON_PYAIRBYTE} absent — ces tests doivent tourner dans l'image de la brique")


def test_verifier_installe_le_connecteur_et_valide_la_config(racine):
    """`check` : c'est aussi ce qui installe le venv du connecteur au premier passage."""
    r = _executer(_job("verifier", racine))
    assert r["ok"] is True, r
    assert r["version_connecteur"]


def test_le_venv_du_connecteur_atterrit_sur_le_volume_pas_dans_l_image(racine):
    """S'il vivait dans la couche image, chaque `up --build` réinstallerait tout et
    retransférerait depuis zéro.

    ⚠ PyAirbyte nomme le venv `.venv-<connecteur>` — avec un point. Un `glob("*")` le rate
    et laisserait croire à une installation hors du volume (piège payé à la main pendant
    la preuve LIVE, d'où `iterdir()`)."""
    installes = [c.name for c in Path(racine, "connecteurs").iterdir()]
    assert any(n.startswith(".venv-") for n in installes), \
        f"aucun venv de connecteur sur le volume : {installes}"


def test_discover_rend_les_flux_du_tiers(racine):
    r = _executer(_job("flux", racine))
    assert r["ok"] is True, r
    assert "users" in r["flux"]


def test_une_sync_transfere_et_rend_un_curseur_non_vide(racine):
    r = _executer(_job("sync", racine))
    assert r["ok"] is True, r
    assert r["nb_enregistrements"] == 300
    assert r["etats"].get("users"), "aucun curseur capté — l'incrémental serait invérifiable"


def test_le_curseur_survit_au_processus_et_est_relu_sans_synchroniser(racine):
    """Le cœur de la reprise : le curseur ne vit pas dans le processus de sync. Un nouveau
    sous-processus, après la mort du précédent, le relit tel quel."""
    r = _executer(_job("etats", racine))
    assert r["ok"] is True, r
    assert r["etats"].get("users"), "curseur perdu entre deux processus"


def test_le_curseur_est_effectivement_repasse_au_connecteur(racine):
    """Ce que PyAirbyte écrit dans le fichier `--state` du connecteur au tour suivant.

    C'est LA vérification que le sprint demande (« état vérifié ») : sans elle,
    l'incrémental n'est qu'une promesse."""
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import airbyte as ab\n"
        "from airbyte.caches.duckdb import DuckDBCache\n"
        f"racine = Path({racine!r})\n"
        f"src = ab.get_source({CONNECTEUR!r}, config={CONFIG!r}, streams={FLUX!r},\n"
        "                    install_if_missing=True, install_root=racine / 'connecteurs')\n"
        "cache = DuckDBCache(db_path=racine / 'cache.duckdb', cache_dir=racine / 'tmp',\n"
        "                    schema_name='integration')\n"
        "fournisseur = cache.get_state_provider(source_name=src._name)\n"
        "print(json.dumps({'etat_transmis': fournisseur.to_state_input_file_text()}))\n"
    )
    import subprocess
    r = subprocess.run([pont.PYTHON_PYAIRBYTE, "-c", script],
                       capture_output=True, timeout=900, env={**os.environ, "DO_NOT_TRACK": "1"})
    ligne = [l for l in r.stdout.decode().splitlines() if l.startswith('{"etat_transmis"')]
    assert ligne, r.stderr.decode()[-1500:]
    etat = json.loads(ligne[-1])["etat_transmis"]
    assert etat and etat != "[]", "le connecteur repartirait de zéro à chaque sync"
    assert "users" in etat


def test_un_connecteur_inexistant_echoue_proprement(racine):
    """Un nom fautif doit rendre une erreur rangeable dans `syncs.erreur`, pas faire
    tomber la brique."""
    r = _executer({"action": "verifier", "connecteur": "source-nexiste-pas-du-tout",
                   "config": {}, "flux": [], "schema": "x", "racine": racine})
    assert r["ok"] is False
    assert r["erreur"]


def test_une_config_invalide_echoue_proprement(racine):
    r = _executer({"action": "verifier", "connecteur": CONNECTEUR,
                   "config": {"count": "pas un nombre"}, "flux": FLUX,
                   "schema": "x", "racine": racine})
    assert r["ok"] is False
