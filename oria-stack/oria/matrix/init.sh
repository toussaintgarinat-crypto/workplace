#!/bin/bash
# Script de démarrage initial de Matrix Synapse pour Oria
# Lancer UNE SEULE FOIS après docker-compose up

echo "=== Initialisation Matrix Synapse pour Oria ==="

# Attendre que Synapse soit prêt
echo "Attente de Synapse sur :8008..."
until curl -sf http://localhost:8008/_matrix/client/versions > /dev/null 2>&1; do
  sleep 2
done
echo "Synapse est prêt !"

# Créer le compte admin oriabot (sender de l'Application Service)
echo "Création du compte oriabot..."
curl -s -X POST http://localhost:8008/_synapse/admin/v1/register \
  -H "Content-Type: application/json" \
  -d '{
    "nonce": "'$(curl -sf http://localhost:8008/_synapse/admin/v1/register | python3 -c "import sys,json; print(json.load(sys.stdin)[\"nonce\"])")'",
    "username": "oriabot",
    "password": "oriabot_dev_password",
    "admin": true,
    "mac": ""
  }' 2>/dev/null || echo "(oriabot existe peut-être déjà)"

echo ""
echo "=== Synapse opérationnel ==="
echo "API Matrix : http://localhost:8008"
echo "Vérification : http://localhost:8008/_matrix/client/versions"
