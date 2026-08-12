"""Intégration RÉELLE avec PyAirbyte (S214) — opt-in, réseau requis.

Sauté par défaut : ces tests installent un vrai connecteur depuis PyPI (venv + réseau,
~1 min au premier passage) et n'ont de sens que dans l'image de la brique, où
`/opt/pyairbyte` existe. Le filet standard reste rapide et hors-ligne.

    docker compose -f briques/connecteurs/docker-compose.yml run --rm --entrypoint "" \
      -e CONNECTEURS_TEST_RESEAU=1 connecteurs \
      sh -c "pip install -q pytest pytest-asyncio && pytest -q test_integration_pyairbyte.py"

────────────────────────────────────────────────────────────────────────────────
⚠ `always_updated: False` DANS LA CONFIG — ce n'est pas un détail de mise au point.

`source-faker` a l'option à `True` par défaut : « Should the updated_at values for every
record be new each sync? ». À `True`, il régénère ses `count` enregistrements à CHAQUE
passage — il écrit bien son curseur, mais rien ne diminue jamais, et l'incrémental paraît
cassé alors qu'il fonctionne. Coût de l'omission, mesuré : une demi-journée passée à
soupçonner la brique, puis PyAirbyte, puis le CDK. Le connecteur a fini par être piloté à
la main, PyAirbyte hors circuit, avec un `--state` écrit à la main : 300 enregistrements
quand même. La cause était dans la config, pas dans la plomberie.

À `False`, le connecteur s'arrête après COUNT enregistrements émis et le delta est réel :
tour 1 = 300, tour 2 = **0**.
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
# `always_updated: False` : sans lui le connecteur régénère tout à chaque sync et le delta
# est invisible (cf. l'avertissement en tête de module). `seed` fixe = données identiques
# d'un passage à l'autre, donc test déterministe.
CONFIG = {"count": 300, "seed": 42, "always_updated": False}
FLUX = ["users"]


@pytest.fixture(scope="module")
def racine(tmp_path_factory):
    """Racine PARTAGÉE : l'installation du venv coûte ~1 min, on ne la refait pas par test.

    Le cache — donc le curseur — y est cumulatif. Les tests qui raisonnent sur le VOLUME
    transféré ne peuvent donc pas s'en servir : ils prennent `racine_neuve`."""
    return str(tmp_path_factory.mktemp("travail"))


@pytest.fixture
def racine_neuve(racine, tmp_path):
    """Cache vierge, mais venvs de connecteur RÉUTILISÉS (lien vers la racine partagée) :
    un test de delta doit partir sans curseur, sans repayer une minute d'installation."""
    neuve = tmp_path / "travail"
    neuve.mkdir()
    (neuve / "connecteurs").symlink_to(Path(racine) / "connecteurs")
    return str(neuve)


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


def test_une_seconde_sync_ne_retransfere_que_le_delta(racine_neuve):
    """**Le critère de sortie de S214.**

    Première sync : 300 enregistrements. Seconde sync, rien de neuf chez le tiers : **0**.
    Le curseur ne bouge pas non plus — c'est ce qui distingue « le tiers n'a rien de neuf »
    de « la brique a perdu son état et a tout relu en silence ».

    Ce test dépend de `always_updated: False` (cf. en-tête du module) : c'est la config qui
    fait de `source-faker` une source incrémentale plutôt qu'un générateur de fixtures.
    """
    premiere = _executer(_job("sync", racine_neuve))
    assert premiere["ok"] is True, premiere
    assert premiere["nb_enregistrements"] == 300
    curseur_apres_premiere = premiere["etats"]["users"]

    seconde = _executer(_job("sync", racine_neuve))
    assert seconde["ok"] is True, seconde
    assert seconde["nb_enregistrements"] == 0, (
        f"le delta n'est pas appliqué : {seconde['nb_enregistrements']} enregistrements "
        "retransférés alors que rien n'a changé chez le tiers")
    assert seconde["etats"]["users"] == curseur_apres_premiere


def test_le_drapeau_complet_ignore_le_curseur_et_retransfere_tout(racine_neuve):
    """L'échappatoire : `complet=true` → `force_full_refresh`. Sans elle, une source dont
    le curseur a dérivé serait définitivement coincée sur un delta faux."""
    assert _executer(_job("sync", racine_neuve))["nb_enregistrements"] == 300
    assert _executer(_job("sync", racine_neuve))["nb_enregistrements"] == 0   # delta

    plein = _executer(_job("sync", racine_neuve, complet=True))
    assert plein["ok"] is True, plein
    assert plein["nb_enregistrements"] == 300, (
        "complet=true n'a pas ignoré le curseur — la personne qui demande un plein "
        "obtiendrait un delta, en silence")


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


def test_extraire_relit_les_lignes_deja_synchronisees(racine):
    """Preuve réelle de action_extraire : source-faker/users (déjà synchronisé par
    `test_une_sync_transfere_et_rend_un_curseur_non_vide` ci-dessus, racine partagée)."""
    r = _executer(_job("extraire", racine, flux_extrait="users"))
    assert r["ok"] is True, r
    assert r["flux"] == "users"
    assert len(r["lignes"]) == 300
    assert "id" in r["lignes"][0]


def test_extraire_un_flux_jamais_synchronise_echoue_proprement(racine_neuve):
    r = _executer(_job("extraire", racine_neuve, flux_extrait="users"))
    assert r["ok"] is False
    assert "jamais synchronisé" in r["erreur"]
