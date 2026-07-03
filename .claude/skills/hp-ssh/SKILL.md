---
name: hp-ssh
description: >
  Accès SSH direct au dossier workplace sur le HP (debian@192.168.1.89,
  /home/debian/workplace). Use when user says "hp-ssh", "/hp-ssh",
  "connecte-toi au hp", "ssh hp", "accède au workplace sur le hp",
  "ouvre le workplace sur le hp", "va sur le hp".
triggers:
  - hp-ssh
---

SSH = `debian@192.168.1.89`, clé `~/.ssh/id_ed25519` (déjà autorisée).
Dossier cible : `/home/debian/workplace`.

Pattern pour toute commande :
```bash
ssh -o BatchMode=yes debian@192.168.1.89 'cd ~/workplace && <commande>'
```

Exécuter directement la commande demandée par l'utilisateur sans charger de runbook ni de documentation supplémentaire.
