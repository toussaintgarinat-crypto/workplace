"""Preuve offline du balayage périodique « app vivante » (S33) — fonctions pures.

On vérifie :
  1. `revue.doit_reviser` : souveraineté (pas de consentement → jamais) ;
  2. respect humain : une revue **validée** en attente n'est pas écrasée ;
  3. une revue absente / appliquée / rejetée → éligible (nouveau cycle) ;
  4. le **contrat manifest** : la tâche `revue-app-vivante` est bien formée pour
     l'horloge S29 (champs requis, cadence numérique, tolere_echec).

Lancer : `python3 test_balayage.py`.
"""
import json
import pathlib

import revue


def run():
    ok = 0

    # 1) Souveraineté : consentement inactif (ou absent) → jamais.
    for partage in ({"actif": False, "entites": ["x"]}, {}, None):
        eligible, raison = revue.doit_reviser(partage, None)
        assert not eligible and raison == "consentement inactif", (partage, eligible, raison)
    print("✅ 1. souveraineté : consentement inactif/absent → non éligible")
    ok += 1

    # 2) Respect humain : revue validée en attente d'application → non écrasée.
    eligible, raison = revue.doit_reviser({"actif": True}, {"statut": "validee"})
    assert not eligible and "validée" in raison, (eligible, raison)
    print("✅ 2. respect humain : revue validée en attente → sautée (pas d'écrasement)")
    ok += 1

    # 3) Consentement actif + revue absente/appliquée/rejetée/propose → éligible.
    for rev in (None, {"statut": "appliquee"}, {"statut": "rejetee"}, {"statut": "propose"}):
        eligible, raison = revue.doit_reviser({"actif": True}, rev)
        assert eligible and raison == "", (rev, eligible, raison)
    print("✅ 3. consentement actif + revue absente/appliquée/rejetée/propose → éligible")
    ok += 1

    # 4) Contrat manifest : la tâche est exploitable par l'horloge S29.
    manifest = json.loads(pathlib.Path("manifest.json").read_text())
    taches = manifest.get("taches") or []
    t = next((x for x in taches if x.get("nom") == "revue-app-vivante"), None)
    assert t, "tâche revue-app-vivante absente du manifest"
    assert t["methode"] == "POST" and t["chemin"] == "/revues/balayage", t
    assert isinstance(t["cadence_heures"], (int, float)) and t["cadence_heures"] > 0, t
    assert t.get("tolere_echec") is True and t.get("idempotent") is True, t
    print("✅ 4. contrat manifest : tâche revue-app-vivante bien formée pour l'horloge")
    ok += 1

    print(f"\n{ok}/4 scénarios OK")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() == 4 else 1)
