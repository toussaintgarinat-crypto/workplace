# livraison (port 6240)

Brique S246 : pilote Dokploy (VM 100) pour l'assistant. Lecture de l'état et des logs
des apps déployées, et trois actions gardées par approbation (redémarrer, déployer,
revenir en arrière).

- Santé : `GET /sante`
- Clé propre : `LIVRAISON_API_KEYS` (jamais `API_KEYS`) ; vide = mode ouvert
- Variables : voir `.env.example` (aucun secret dans le compose)
- Tests : `python3 -m pytest -q -p no:cacheprovider`
