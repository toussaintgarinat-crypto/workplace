"""S230 — filet repo-wide (motif tests/test_contrat_capacites.py, S210) : aucune capacité
manifeste n'expose la création/modification de source, ni de connecteur/venture_id caché,
à l'assistant. `POST /sources`, `PATCH /sources/{id}` doivent rester absents."""
import json
from pathlib import Path

import main


def test_aucune_capacite_n_expose_lecriture_de_source():
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    ecritures = {(c["methode"], c["chemin"]) for c in manifest.get("capacites", [])}
    assert ("POST", "/sources") not in ecritures
    assert ("PATCH", "/sources/{source_id}") not in ecritures


def test_toutes_les_capacites_du_manifeste_existent_bien_comme_routes():
    """Motif S210 (`connexion_envoyer`, routes mortes) : une capacité dont le chemin
    manifeste ne correspond à AUCUNE route réelle est un 404 systématique invisible."""
    import re
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins_reels = {
        (re.sub(r"\{[^}]*\}", "{}", r.path), m)
        for r in main.app.routes if hasattr(r, "path") and hasattr(r, "methods")
        for m in r.methods
    }
    for c in manifest.get("capacites", []):
        chemin_normalise = re.sub(r"\{[^}]*\}", "{}", c["chemin"])
        assert (chemin_normalise, c["methode"]) in chemins_reels, \
            f"capacité « {c['nom']} » ({c['methode']} {c['chemin']}) — route morte"
