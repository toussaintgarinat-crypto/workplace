.PHONY: build up down logs test

build:
	docker compose build

up:
	docker compose up -d --build
	@echo "Brique ETL démarrée sur http://localhost:5200"
	@echo "Santé : http://localhost:5200/sante"
	@echo "Docs  : http://localhost:5200/docs"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	@echo "=== Test santé ==="
	curl -s http://localhost:5200/sante | python3 -m json.tool
	@echo ""
	@echo "=== Test liste documents ==="
	curl -s http://localhost:5200/documents | python3 -m json.tool
