.PHONY: dev up down migrate seed lint format frontend mcp cli install

dev:
	cd backend && ./venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker compose up -d

down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m scripts.seed

test:
	cd backend && python -m pytest tests/ -v --tb=short

test-cov:
	cd backend && python -m pytest tests/ -v --tb=short --cov=app --cov-report=term

lint:
	cd backend && ruff check .
	cd backend && mypy .

format:
	cd backend && ruff format .

install:
	cd backend && pip install -r requirements.txt

cli:
	cd cli && python3 main.py

frontend:
	cd frontend && npm run dev

mcp:
	cd mcp-server && go run main.go
