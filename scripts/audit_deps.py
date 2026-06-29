#!/usr/bin/env python3
"""Audit d'alignement des dépendances (S117).

Compare chaque `*/requirements.txt` aux versions de `constraints-workplace.txt` et
liste les écarts pour les paquets d'infrastructure partagés. Sert à PILOTER le rollout
des contraintes (brique par brique) : tant qu'il reste des écarts, ce script les montre ;
quand tout est aligné, il sort 0. Lancé par `make deps-audit` (hors `make test`, car
l'alignement est volontairement progressif).

Sortie : code 1 s'il reste des écarts (paquet contraint épinglé à une autre version),
0 sinon. Les paquets non épinglés (flottants) sont signalés mais non bloquants.
"""
import glob
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CONTRAINTES = RACINE / "constraints-workplace.txt"
_PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s#;]+)")
_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*([<>=!~].*)?$")


def _norm(n):
    return n.lower().replace("_", "-")


def charger_contraintes():
    cibles = {}
    for line in CONTRAINTES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PIN.match(line)
        if m:
            cibles[_norm(m.group(1))] = m.group(2)
    return cibles


def main():
    cibles = charger_contraintes()
    reqs = (glob.glob(str(RACINE / "core/requirements.txt"))
            + glob.glob(str(RACINE / "briques/*/requirements.txt"))
            + glob.glob(str(RACINE / "oria-stack/*/requirements.txt")))
    ecarts, flottants = [], []
    for r in sorted(reqs):
        comp = Path(r).parent.name
        for raw in Path(r).read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#") or raw.startswith("-"):
                continue
            mp = _PIN.match(raw)
            if mp:
                nom, ver = _norm(mp.group(1)), mp.group(2)
                if nom in cibles and ver != cibles[nom]:
                    ecarts.append((comp, nom, ver, cibles[nom]))
                continue
            mn = _NAME.match(raw)
            if mn:
                nom = _norm(mn.group(1))
                if nom in cibles and not mn.group(2):
                    flottants.append((comp, nom, cibles[nom]))

    print(f"Contraintes partagées : {', '.join(f'{k}=={v}' for k, v in cibles.items())}\n")
    if ecarts:
        print(f"❌ {len(ecarts)} écart(s) de version (paquet contraint épinglé ailleurs) :")
        for comp, nom, ver, cible in ecarts:
            print(f"   {comp:14} {nom:18} {ver:10} → attendu {cible}")
    else:
        print("✅ Aucun écart de version sur les paquets contraints.")
    if flottants:
        print(f"\n⚠️  {len(flottants)} paquet(s) contraint(s) mais NON épinglé(s) "
              "(adopteront la contrainte via `-c`) :")
        for comp, nom, cible in flottants:
            print(f"   {comp:14} {nom:18} (flottant) → {cible}")
    return 1 if ecarts else 0


if __name__ == "__main__":
    sys.exit(main())
