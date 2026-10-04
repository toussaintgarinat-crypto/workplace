# Mesure de reprise S237

`measure.py` chronomètre des phases réelles avec une horloge monotone, arrête l'exercice au premier échec et conserve stdout/stderr dans des fichiers 0600 sous un répertoire neuf 0700. Les commandes sont des listes argv, sans shell ; ne pas passer de secrets en arguments. Les tâches distantes doivent utiliser les playbooks S237 et leurs gardes. Cet outil de mesure ne constitue pas lui-même une barrière réseau ou une autorisation de cible.

Le plan JSON privé contient `scope`, `metadata` et `phases`. Chaque phase contient un nom unique (`[a-z][a-z0-9_-]{0,63}`), `argv` et éventuellement `timeout_seconds` (défaut : 28 800 s). Métadonnées admises : `revision` (SHA Git complet), `generation`, `target_id`, `cache_condition` (libellés alphanumériques avec tirets/underscores) et `vm_acquisition_measured` (booléen). Ne pas y mettre de secrets.

```sh
python3 outils/reconstruction/measure.py \
  --plan /chemin/prive/plan-reprise.json \
  --target /chemin/prive/nouvelle-mesure
```

Le parent du répertoire de mesure doit déjà exister. Un chemin existant, traversant ou un parent symlink est refusé ; sur macOS utiliser les chemins canoniques `/private/tmp` et `/private/var`.

Phases à chronométrer pour le RTO : acquisition de VM si observable, prérequis Debian/Docker, récupération et vérification de sauvegarde indépendante, acquisition du code/images et builds, isolation réseau vérifiée, restauration native et raccordement des données, démarrage simultané, contrôles de données et métier. L'ordre récupération/build/isolation doit permettre les téléchargements sans démarrer les producteurs avant le blocage des sorties. Le second passage, la mise à jour ciblée et le rollback sont des exercices séparés du RTO initial.

Le rapport donne `execution_complete` pour l'exécution des commandes. **`recovery_verified` reste toujours faux** : une suite de codes retour 0 ne prouve ni intégrité des données, ni santé métier, ni couverture complète du stack. La validation humaine du rapport S237 doit se fonder sur les preuves des sondes, de l'isolation et des contrôles de restauration. Ne pas publier un RTO complet si l'acquisition de VM, la restauration ou une partie du stack n'a pas été mesurée.

En cas de timeout le groupe de processus est tué, SSH/Ansible compris ; une commande distante déjà lancée peut continuer sur la VM. Le rapport ne prétend pas l'annuler : inspecter la cible avant toute relance, sans nettoyer des ressources non identifiées. Les logs peuvent contenir des secrets issus des outils appelés ; ne pas les publier.

Tests locaux : `python3.11 -m unittest discover -s outils/reconstruction -p 'test_*.py' -v`. Ces tests utilisent de petits processus locaux et ne mesurent pas le temps de reprise de Workplace.
