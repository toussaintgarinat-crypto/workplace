#!/usr/bin/env bash
set -euo pipefail

echo "=== Memory — Setup ==="

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 is required"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Error: node is required"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Error: docker is required"; exit 1; }
command -v go >/dev/null 2>&1 || { echo "Warning: go is recommended for MCP Server"; }

# Copy .env if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit it with your settings"
fi

# Backend setup
echo ""
echo "--- Backend ---"
cd backend
python3 -m venv .venv 2>/dev/null || true
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
elif [ -f .venv/Scripts/activate ]; then
    source .venv/Scripts/activate
fi
pip install -r requirements.txt
cd ..

# Frontend setup
echo ""
echo "--- Frontend ---"
cd frontend
npm install
cd ..

# MCP Server
if command -v go >/dev/null 2>&1; then
    echo ""
    echo "--- MCP Server ---"
    cd mcp-server
    go mod download
    cd ..
fi

# Start database
echo ""
echo "--- Database ---"
docker compose up -d
echo "Waiting for PostgreSQL..."
sleep 3

# Run migrations and seed
echo ""
echo "--- Migrations & Seed ---"
cd backend
if [ -f alembic.ini ]; then
    alembic upgrade head 2>/dev/null || echo "Migrations skipped (Alembic not configured)"
fi
cd ..

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Commands:"
echo "  make dev       — Start backend API"
echo "  cd frontend && npm run dev  — Start frontend"
echo "  make mcp       — Start MCP Server"
echo "  make seed      — Load demo data"
