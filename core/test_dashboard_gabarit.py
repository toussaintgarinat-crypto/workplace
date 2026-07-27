"""S208 — le gabarit du dashboard vit dans un fichier, plus dans une chaîne Python.

`core/routers/dashboard.py` faisait 3527 lignes, dont 3460 de HTML/CSS/JS embarqué : 66 % de
tout `core/routers/`. Sortir le gabarit dans `core/dashboard.html` ramène le module à 89
lignes de logique lisible.

Ces tests gardent les deux invariants que l'extraction pouvait casser :
  1. le fichier doit être TROUVÉ à l'exécution — il est livré par `COPY core/ .`, mais un
     `.dockerignore` malheureux ou un déplacement le rendrait introuvable, et le Cœur
     planterait à l'import, pas à la première requête ;
  2. tous les marqueurs `__*_UI_URL__` doivent être substitués — un marqueur oublié dans le
     gabarit s'afficherait tel quel dans une iframe, en silence.
"""
import os
import re
from pathlib import Path

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from routers import dashboard  # noqa: E402

client = TestClient(main.app)


def test_le_gabarit_est_un_fichier_a_cote_du_code():
    chemin = Path(dashboard.__file__).parent.parent / "dashboard.html"
    assert chemin.is_file(), "gabarit introuvable — le Cœur ne démarrerait pas"
    assert chemin.stat().st_size > 100_000, "gabarit suspicieusement petit"


def test_le_module_reste_de_la_logique_pas_du_gabarit():
    """Garde-fou contre le retour du HTML dans le code : c'est ce qui avait fait gonfler ce
    module jusqu'à 66 % du dossier `routers/`."""
    lignes = Path(dashboard.__file__).read_text(encoding="utf-8").count("\n")
    assert lignes < 200, f"dashboard.py a regrossi ({lignes} lignes) — le gabarit y revient ?"


def test_aucun_marqueur_ne_survit_dans_la_page_servie():
    page = client.get("/dashboard").text
    restants = set(re.findall(r"__[A-Z_]+_URL__", page))
    assert not restants, f"marqueurs non substitués rendus au navigateur : {restants}"


def test_la_page_est_servie_entiere():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert r.text.rstrip().endswith("</html>"), "page tronquée"
