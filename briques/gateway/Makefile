.PHONY: start stop logs reset sync

# Les modèles gratuits ne sont plus entretenus par un script lancé à la main : la brique
# `gateway-sync` (démarrée par ce compose) le fait par l'API LiteLLM, au boot puis chaque
# jour via l'horloge du Cœur. `make sync` reste offert pour forcer un passage immédiat.
# Cf. ADR docs/decisions/2026-07-27-sync-modeles-gratuits-gateway.md.
start:
	docker compose up -d

sync:
	@curl -fsS -X POST http://localhost:4002/sync \
	  $${GATEWAY_SYNC_KEY:+-H "X-API-Key: $$GATEWAY_SYNC_KEY"} && echo

stop:
	docker compose down

logs:
	docker compose logs -f

reset:
	docker compose down -v
