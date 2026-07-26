"""Utilitaires partagés du projet Agent Personnel de Création.

Modules :
- redis_client    : wrapper async paramétrable + namespace + lock + publish
- fastapi_setup   : setup_cors (CSV) + setup_logging (JSON optionnel)
- health          : HealthBuilder — schéma JSON `/health` commun (S101)
- http_client     : S2SClient — wrapper httpx async retry + circuit breaker (S99)
- jobs            : Redis Streams — enqueue + JobWorker durables (S125)

NB (S120) : la validation JWT Keycloak a quitté ce paquet pour la lib partagée du
monorepo `shared.workplace_auth` (source de vérité unique). Importer de là.
"""

__version__ = "0.4.0"
