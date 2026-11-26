"""EXECUTEUR_KEY ne doit pas vivre dans le .env racine (chargé par ~45 briques, exporté par la
sauvegarde) : fichier local à la brique, facultatif."""
import re
from pathlib import Path

ICI = Path(__file__).parent


def test_env_file_local_a_la_brique_et_aucune_cle_litterale():
    t = (ICI / "docker-compose.yml").read_text()
    assert re.search(r"- path: \./\.env\s*\n\s*required: false", t)
    assert "EXECUTEUR_KEY=" not in t
