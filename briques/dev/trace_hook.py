#!/usr/bin/env python3
"""Hook Claude Code → trace FR (S89). Branché en `PreToolUse` quand la trace est active.

Claude Code passe l'évènement du hook en JSON sur stdin (`tool_name`, `tool_input`, …). On le
traduit en phrase française et on l'ajoute au journal de trace du chantier (chemin en argv[1]).
Le hook est volontairement SILENCIEUX et tolérant : il ne doit jamais faire échouer le run de
l'agent (sortie 0 quoi qu'il arrive)."""
import json
import os
import sys

# Permet d'importer `traceur` même quand Claude Code lance ce script depuis le worktree.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    fichier = sys.argv[1]
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — stdin vide/mal formé : on n'embête pas l'agent
        return 0
    try:
        import traceur
        phrase = traceur.phrase_pour_evenement(payload)
        if phrase:
            traceur.Traceur(fichier).noter(phrase, type="outil")
    except Exception:  # noqa: BLE001 — la trace est un bonus, jamais un point de panne
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
