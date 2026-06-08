#!/bin/bash
# Initialisation post-démarrage Dendrite — lancer UNE SEULE FOIS après docker-compose up

DENDRITE_URL="${MATRIX_HOMESERVER_URL:-http://localhost:8008}"
SHARED_SECRET="${MATRIX_REGISTRATION_SHARED_SECRET}"

echo "=== Initialisation Dendrite pour Oria ==="

echo "Attente de Dendrite sur ${DENDRITE_URL}..."
until curl -sf "${DENDRITE_URL}/_matrix/client/versions" > /dev/null 2>&1; do
  sleep 2
done
echo "Dendrite est prêt !"

# Récupérer le nonce pour la création admin
NONCE=$(curl -sf "${DENDRITE_URL}/_dendrite/admin/register" | python3 -c "import sys,json; print(json.load(sys.stdin)['nonce'])" 2>/dev/null)
if [ -z "$NONCE" ]; then
  echo "Impossible de récupérer le nonce — MATRIX_REGISTRATION_SHARED_SECRET est-il défini ?"
  exit 1
fi

# Calculer le MAC HMAC-SHA1
MAC=$(printf "%s\n%s\n%s\nadmin" "$NONCE" "oriabot" "oriabot_dev_password" \
  | openssl dgst -sha1 -hmac "$SHARED_SECRET" | sed 's/^.*= //')

echo "Création du compte oriabot..."
RESPONSE=$(curl -s -X POST "${DENDRITE_URL}/_dendrite/admin/register" \
  -H "Content-Type: application/json" \
  -d "{\"nonce\":\"${NONCE}\",\"username\":\"oriabot\",\"password\":\"oriabot_dev_password\",\"admin\":true,\"mac\":\"${MAC}\"}")

echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print('oriabot créé :', d.get('user_id', d))" \
  2>/dev/null || echo "(oriabot existe peut-être déjà ou l'AS le crée automatiquement)"

echo ""
echo "=== Dendrite opérationnel ==="
echo "API Matrix : ${DENDRITE_URL}"
echo "Vérification : ${DENDRITE_URL}/_matrix/client/versions"
