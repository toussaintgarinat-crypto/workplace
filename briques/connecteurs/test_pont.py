"""Le protocole de la cloison (S214) — éprouvé avec de FAUX exécuteurs.

Ces tests n'installent pas PyAirbyte : ils remplacent l'exécuteur par un petit script
Python qui reproduit chacun des comportements redoutés. C'est ce qui permet de tenir le
protocole dans le filet standard, sans les 700 Mo de la librairie ni le réseau.

La vraie librairie est éprouvée séparément (`test_integration_pyairbyte.py`, opt-in).
"""
import asyncio
import os
import stat
import sys

import pytest

import pont


@pytest.fixture
def faux_executeur(tmp_path, monkeypatch):
    """Fabrique un exécuteur bidon et branche `pont` dessus."""
    def fabriquer(code: str):
        script = tmp_path / "faux.py"
        script.write_text(code, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(pont, "PYTHON_PYAIRBYTE", sys.executable)
        monkeypatch.setattr(pont, "EXECUTEUR", str(script))
        return script
    return fabriquer


def _executer(job=None, **kw):
    return asyncio.run(pont.executer(job or {"action": "sync"}, **kw))


# ── Le piège qui a dicté le design ───────────────────────────────────────────

def test_le_bruit_de_pyairbyte_ne_corrompt_pas_le_protocole(faux_executeur):
    """PyAirbyte écrit ses barres de progression `rich` sur STDOUT. Si le protocole y
    vivait aussi, la réponse serait noyée — de façon intermittente, donc invisible en
    test et fatale en production. On vérifie qu'on retrouve la réponse au milieu du bruit.
    """
    faux_executeur(
        "import sys, json\n"
        "sys.stdin.read()\n"
        "print('─' * 60)\n"
        "print('Sync Progress: source-github -> DuckDBCache')\n"
        "print(' • Read 1,204 records over 3.2 seconds')\n"
        "print('{ceci ressemble à du JSON mais ne l est pas')\n"
        "print(json.dumps({'ok': True, 'nb_enregistrements': 1204}))\n"
    )
    assert _executer() == {"ok": True, "nb_enregistrements": 1204}


def test_la_cloison_reelle_renvoie_le_bruit_sur_stderr():
    """`pont/executer.py` duplique le vrai stdout puis branche fd 1 sur stderr, AVANT
    d'importer airbyte. On l'éprouve pour de vrai : un `print()` après import doit partir
    dans les logs, et le canal du protocole rester propre."""
    import subprocess
    code = (
        "import sys, os\n"
        "_CANAL = os.fdopen(os.dup(1), 'w'); os.dup2(2, 1)\n"
        "print('bruit de librairie qui croit parler à un terminal')\n"
        "sys.stdout.write('encore du bruit\\n')\n"
        "_CANAL.write('{\"ok\": true}\\n'); _CANAL.flush()\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=30)
    assert r.stdout.decode().strip() == '{"ok": true}'
    assert "bruit de librairie" in r.stderr.decode()


# ── Échecs : tous rendus en donnée, jamais en exception ──────────────────────

def test_un_connecteur_qui_echoue_rend_une_erreur_lisible(faux_executeur):
    faux_executeur(
        "import sys, json\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'ok': False, 'erreur': 'ConnectorError: Config validation failed'}))\n"
        "sys.exit(1)\n"
    )
    r = _executer()
    assert r["ok"] is False and "Config validation failed" in r["erreur"]


def test_un_processus_mort_sans_rien_dire_rend_la_queue_de_stderr(faux_executeur):
    """OOM, kill, import cassé : l'opérateur ne devrait pas avoir à ouvrir `docker logs`."""
    faux_executeur(
        "import sys\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('ModuleNotFoundError: No module named airbyte\\n')\n"
        "sys.exit(3)\n"
    )
    r = _executer()
    assert r["ok"] is False
    assert "code 3" in r["erreur"]
    assert "No module named airbyte" in r["journal"]


def test_une_sortie_totalement_vide_ne_leve_pas(faux_executeur):
    faux_executeur("import sys\nsys.stdin.read()\n")
    assert _executer()["ok"] is False


def test_un_processus_qui_pend_est_tue_au_delai(faux_executeur):
    """Sans plafond, un connecteur bloqué laisse une sync « en_cours » éternelle qui
    empêche toutes les suivantes (garde d'idempotence)."""
    faux_executeur("import sys, time\nsys.stdin.read()\ntime.sleep(60)\n")
    r = _executer(timeout=1)
    assert r["ok"] is False and "délai dépassé" in r["erreur"]


def test_pont_indisponible_leve_car_c_est_une_image_cassee(monkeypatch):
    """Distinct d'une erreur d'usager : PyAirbyte absent = l'image est mal construite."""
    monkeypatch.setattr(pont, "PYTHON_PYAIRBYTE", "/nexiste/pas/python")
    assert pont.disponible() is False
    with pytest.raises(pont.PontIndisponible):
        _executer()


# ── La config ne fuit pas par la ligne de commande ───────────────────────────

def test_la_config_arrive_par_stdin_et_pas_par_argv(faux_executeur):
    """`ps` dans le conteneur rendrait un jeton GitHub lisible par tout processus."""
    faux_executeur(
        "import sys, json\n"
        "recu = json.loads(sys.stdin.read())\n"
        "print(json.dumps({'ok': True, 'argv': sys.argv[1:],\n"
        "                  'jeton_recu': recu['config']['token']}))\n"
    )
    r = _executer({"action": "sync", "config": {"token": "ghp_tres_secret"}})
    assert r["jeton_recu"] == "ghp_tres_secret"
    assert not any("ghp_tres_secret" in a for a in r["argv"])


def test_la_telemetrie_est_coupee_dans_l_environnement_du_sous_processus(faux_executeur):
    """PyAirbyte annonce à l'import que le rapport d'usage anonyme est ACTIF par défaut."""
    faux_executeur(
        "import sys, json, os\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'ok': True, 'do_not_track': os.environ.get('DO_NOT_TRACK')}))\n"
    )
    assert _executer()["do_not_track"] == "1"


# ── Cloisonnement des schémas ────────────────────────────────────────────────

def test_deux_sources_du_meme_connecteur_ont_des_schemas_distincts():
    """Deux dépôts GitHub chez la même personne ne doivent partager ni tables ni curseur."""
    assert pont.schema_de("alice", 1) != pont.schema_de("alice", 2)


def test_deux_personnes_ont_des_schemas_distincts():
    assert pont.schema_de("alice", 1) != pont.schema_de("bob", 1)


def test_le_schema_est_un_identifiant_sql_licite():
    """Un tenant est une empreinte ou un `perso:<id>` — le « : » n'est pas licite en SQL."""
    schema = pont.schema_de("perso:marina-durand", 3)
    assert schema.replace("_", "").isalnum() and not schema[0].isdigit()
