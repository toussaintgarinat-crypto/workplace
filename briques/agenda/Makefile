.PHONY: build up down logs test

build:
	docker compose build

up:
	docker compose up -d --build
	@echo "Brique Agenda démarrée sur http://localhost:8400"
	@echo "Santé : http://localhost:8400/health"
	@echo "Docs  : http://localhost:8400/docs"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@echo "=== Test santé ==="
	curl -s http://localhost:8400/health | python3 -m json.tool
	@echo ""
	@echo "=== Calendriers (X-User-Id: perso) ==="
	curl -s http://localhost:8400/calendars -H "X-User-Id: perso" | python3 -m json.tool
