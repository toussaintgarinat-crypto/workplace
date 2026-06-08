.PHONY: build up down logs test

build:
	docker compose build

up:
	docker compose up -d --build
	@echo "Brique Mémoire démarrée sur http://localhost:5600"
	@echo "Santé : http://localhost:5600/sante"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@echo "=== Santé ==="
	curl -s http://localhost:5600/sante | python3 -m json.tool
	@echo "=== Retenir ==="
	curl -s -X POST http://localhost:5600/retenir -H 'Content-Type: application/json' \
	  -d '{"contenu":"Test de mémoire Workplace","titre":"Test"}' | python3 -m json.tool
	@echo "=== Rappeler ==="
	curl -s "http://localhost:5600/rappeler?q=test" | python3 -m json.tool
