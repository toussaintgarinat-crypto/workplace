"""Bibliothèques partagées du monorepo Workplace (S118+).

Source unique des briques d'infrastructure communes au Cœur et aux briques :
- `llm_client` : appel résilient au Gateway LiteLLM (backoff, extraction JSON).
Livrée dans chaque image via un build-context = racine du repo (cf. les Dockerfile
qui `COPY shared/`), et rendue importable en test natif par le conftest des briques.
"""
