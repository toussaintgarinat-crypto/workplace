.PHONY: start stop logs build reset core-test core-models

start:
	@bash setup.sh

stop:
	docker compose -f docker-compose.standalone.yml down

logs:
	docker compose -f docker-compose.standalone.yml logs -f

build:
	docker compose -f docker-compose.standalone.yml build --no-cache

reset:
	docker compose -f docker-compose.standalone.yml down -v
	@echo "All data volumes removed"

# ── core (migration Python strangler, S126) ──────────────────
core-test:
	cd core && PYTHONPATH=. pytest tests/ --cov=app --cov-report=term-missing --cov-fail-under=30

core-models:
	cd core && ./scripts/gen_models.sh
