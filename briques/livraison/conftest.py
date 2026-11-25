import os
os.environ["LIVRAISON_API_KEYS"] = ""      # mode ouvert en test
os.environ["DOKPLOY_URL"] = "http://dokploy.test"
os.environ["DOKPLOY_API_KEY"] = "cle-de-test"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _donnees_isolees(tmp_path, monkeypatch):
    """Le repère de rollback est persisté : un dossier neuf par test, sinon les tests se contaminent."""
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path / "data"))
