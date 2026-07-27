"""S204 — `Settings` doit survivre à un .env partagé.

Le .env de ce monorepo est commun à docker-compose, Postgres et aux autres briques ; il
contient donc quantité de clés qui ne concernent PAS ce service. `env_file` les fait toutes
entrer dans la validation, et le défaut de pydantic-settings (`extra="forbid"`) transformait
chacune d'elles en `ValidationError` À L'IMPORT du module — c'est-à-dire en backend qui ne
démarre pas. Ces tests figent l'arbitraire retenu (`extra="ignore"`, motif briques/forge).
"""
import sys
import textwrap
from pathlib import Path

# Placé à la RACINE de la brique et non dans memory/backend/tests/ : le conftest de ce
# dossier ouvre une vraie session Postgres, si bien qu'un test de configuration pure y
# devenait inexécutable sans base — alors qu'il n'en a aucun besoin.
sys.path.insert(0, str(Path(__file__).parent / "memory" / "backend"))

from app.config import Settings  # noqa: E402


def test_une_variable_etrangere_ne_fait_pas_echouer_settings(tmp_path, monkeypatch):
    """Cas réel : MEMOIRE_DB_PASSWORD est lue par le compose, jamais par ce service."""
    env = tmp_path / ".env"
    env.write_text(textwrap.dedent("""
        MEMOIRE_DB_PASSWORD=pg-un-secret-du-compose
        UNE_VARIABLE_QUI_NE_NOUS_CONCERNE_PAS=peu importe
        JWT_SECRET=secret-de-test
    """).strip())
    monkeypatch.chdir(tmp_path)

    s = Settings(_env_file=str(env))

    assert s.jwt_secret == "secret-de-test", "les clés connues restent lues"
    assert not hasattr(s, "memoire_db_password"), "les clés étrangères sont ignorées, pas gardées"


def test_les_valeurs_par_defaut_restent_intactes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings(_env_file=str(tmp_path / "absent.env"))
    assert s.llm_provider == "openrouter"
    assert s.tier_hot_days == 30
