import json
import os
from pathlib import Path

BRIQUES_DIR = Path(os.environ.get("BRIQUES_DIR", str(Path(__file__).parent.parent / "briques")))


class Registre:
    def __init__(self):
        self.briques: dict = {}

    def charger(self):
        self.briques = {}
        if not BRIQUES_DIR.exists():
            print(f"[registre] Répertoire briques introuvable : {BRIQUES_DIR}")
            return
        for manifest_path in sorted(BRIQUES_DIR.glob("*/manifest.json")):
            try:
                with open(manifest_path) as f:
                    data = json.load(f)
                nom = data.get("nom")
                if nom:
                    self.briques[nom] = data
                else:
                    print(f"[registre] manifest sans 'nom' ignoré : {manifest_path}")
            except Exception as e:
                print(f"[registre] Erreur lecture {manifest_path}: {e}")
        print(f"[registre] {len(self.briques)} brique(s) chargée(s) : {list(self.briques.keys())}")
