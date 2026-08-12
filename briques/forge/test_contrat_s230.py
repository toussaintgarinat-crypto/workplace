"""S230 — filet repo-wide : les proxys internes (GET/PATCH /ventures/{vid},
crm/import-lot avec venture_id) existent bien comme routes réelles ET restent absents des
capacités assistant du manifeste."""
import json
import re
from pathlib import Path

import main


def test_les_deux_nouvelles_routes_ventures_existent_reellement():
    chemins = {
        (re.sub(r"\{[^}]*\}", "{}", r.path), m)
        for r in main.app.routes if hasattr(r, "path") and hasattr(r, "methods")
        for m in r.methods
    }
    assert ("/ventures/{}", "GET") in chemins
    assert ("/ventures/{}", "PATCH") in chemins


def test_lecture_ecriture_venture_absentes_du_manifeste():
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins_capacites = {c["chemin"] for c in manifest.get("capacites", [])}
    assert "/ventures/{vid}" not in chemins_capacites
    assert "/ventures/{id}" not in chemins_capacites
