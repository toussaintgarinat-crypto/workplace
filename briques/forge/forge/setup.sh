#!/bin/bash
set -e

echo "=== Forge Standalone Setup ==="

# Vérification des prérequis
command -v docker >/dev/null 2>&1 || { echo "Erreur : Docker non trouvé. Installer Docker Desktop."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Erreur : docker compose (v2) non trouvé."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "Erreur : openssl non trouvé."; exit 1; }

if [ ! -f .env ]; then
    cp .env.example .env

    ENCRYPTION_KEY=$(openssl rand -base64 32 | tr -d '\n')
    KEYCLOAK_PASS=$(openssl rand -base64 16 | tr -d '\n')

    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|change_this_32_char_random_key!!|$ENCRYPTION_KEY|g" .env
        sed -i '' "s|change_this_in_production|$KEYCLOAK_PASS|g" .env
    else
        sed -i "s|change_this_32_char_random_key!!|$ENCRYPTION_KEY|g" .env
        sed -i "s|change_this_in_production|$KEYCLOAK_PASS|g" .env
    fi

    echo "  .env created — save this password:"
    echo "  KEYCLOAK_ADMIN_PASSWORD = $KEYCLOAK_PASS"
    echo ""
else
    echo "  .env already exists — skipping generation"
fi

docker compose -f docker-compose.standalone.yml up -d --build

echo ""
echo "Forge is starting (Keycloak takes ~60s on first boot)"
echo ""
echo "  Frontend : http://localhost:3000"
echo "  API      : http://localhost:8600/api/health"
echo "  Keycloak : http://localhost:8080"
echo "  Qdrant   : http://localhost:6333"
