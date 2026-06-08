.PHONY: build up down logs test

build:
	docker compose build

up:
	docker compose up -d --build
	@echo "Brique Forge démarrée :"
	@echo "  · core      → http://localhost:8600  (Swagger /docs)"
	@echo "  · adaptateur → http://localhost:5700  (contrat Workplace /sante, /capacites)"
	@echo "  · frontend  → http://localhost:3000  (SPA intégrée — onglet Forge du dashboard, S19)"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@echo "=== Core : santé publique (/api/health) ==="
	curl -s http://localhost:8600/api/health | python3 -m json.tool
	@echo "=== Core : santé interne (/health, teste la DB) ==="
	curl -s http://localhost:8600/health | python3 -m json.tool
	@echo "=== Adaptateur : /sante (agrégée) ==="
	curl -s http://localhost:5700/sante | python3 -m json.tool
	@echo "=== Adaptateur : /capacites ==="
	curl -s http://localhost:5700/capacites | python3 -m json.tool
