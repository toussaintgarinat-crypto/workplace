.PHONY: build up down logs restart reload test

build:
	docker compose build

up:
	docker compose up -d
	@echo ""
	@echo "Cœur Workplace démarré :"
	@echo "  API      → http://localhost:5100"
	@echo "  Docs     → http://localhost:5100/docs"
	@echo "  Briques  → http://localhost:5100/briques"
	@echo "  Santé    → http://localhost:5100/health"

down:
	docker compose down

logs:
	docker compose logs -f core

restart:
	docker compose restart core

reload:
	@curl -s -X POST http://localhost:5100/briques/reload | python3 -m json.tool

test:
	@echo "=== Health ==="
	@curl -s http://localhost:5100/health | python3 -m json.tool
	@echo ""
	@echo "=== Briques ==="
	@curl -s http://localhost:5100/briques | python3 -m json.tool
	@echo ""
	@echo "=== Santé globale ==="
	@curl -s http://localhost:5100/sante-globale | python3 -m json.tool
