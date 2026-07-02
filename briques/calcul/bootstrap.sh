#!/bin/sh
# bootstrap.sh — Un muscle en UNE commande.
#
# Usage :
#   curl -fsSL https://<CALCUL_MESH>/muscle/bootstrap.sh | \
#     MUSCLE_KEY=<clé> CALCUL_MESH=<host:port> sh
#
# Variables (passées à l'environnement, jamais dans le .env du serveur) :
#   MUSCLE_KEY       — clé API requise pour s'inscrire (X-API-Key)
#   CALCUL_MESH      — host:port mesh de la brique calcul (ex. 100.x.x.x:5990)
#   SETUP_KEY        — clé d'enrôlement NetBird (optionnel si déjà dans le mesh)
#   MUSCLE_MODELE    — nom de modèle à télécharger (override de la détection RAM)
#   MUSCLE_DRYRUN    — si non vide : détecte + affiche le payload, n'installe rien
#
# Idempotent : relancer le script ré-inscrit le même id (dérivé du hostname) sans doublon.
# POSIX sh uniquement — aucune dépendance bash/zsh.

set -e

# ── Couleurs pour les messages ────────────────────────────────────────────────
_ok()  { printf '\033[32m✓ %s\033[0m\n' "$*"; }
_ko()  { printf '\033[31m✗ %s\033[0m\n' "$*"; }
_inf() { printf '\033[34m→ %s\033[0m\n' "$*"; }
_wr()  { printf '\033[33m⚠ %s\033[0m\n' "$*"; }

# ── Vérifications initiales ───────────────────────────────────────────────────
if [ -z "$MUSCLE_KEY" ]; then
  _ko "MUSCLE_KEY est vide — passez-la en variable : MUSCLE_KEY=... sh bootstrap.sh"
  exit 1
fi
if [ -z "$CALCUL_MESH" ]; then
  _ko "CALCUL_MESH est vide — passez l'adresse mesh de la brique calcul : CALCUL_MESH=100.x.x.x:5990"
  exit 1
fi

MUSCLE_ID="muscle-$(hostname | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-' | sed 's/-*$//')"
_inf "Identifiant muscle : $MUSCLE_ID"

# ── Étape 1 : rejoindre le mesh NetBird ──────────────────────────────────────
IP_MESH=""
if command -v netbird >/dev/null 2>&1 || [ -f /usr/sbin/netbird ]; then
  STATUS=$(netbird status 2>/dev/null || true)
  if echo "$STATUS" | grep -qi "Connected"; then
    # Récupérer l'IP mesh depuis la sortie de netbird status
    IP_MESH=$(echo "$STATUS" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1 || true)
    _ok "Mesh NetBird : déjà connecté ($IP_MESH)"
  fi
fi

if [ -z "$IP_MESH" ] && [ -n "$SETUP_KEY" ]; then
  _inf "Installation/connexion NetBird..."
  if [ -z "$MUSCLE_DRYRUN" ]; then
    curl -fsSL https://pkgs.netbird.io/install.sh | sh >/dev/null 2>&1 || true
    netbird up --setup-key "$SETUP_KEY" >/dev/null 2>&1 || true
    sleep 3
    STATUS=$(netbird status 2>/dev/null || true)
    IP_MESH=$(echo "$STATUS" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1 || true)
    if [ -n "$IP_MESH" ]; then
      _ok "Mesh NetBird : connecté ($IP_MESH)"
    else
      _wr "Mesh NetBird : connexion en cours — continuons avec l'IP locale"
    fi
  else
    _inf "[DRY-RUN] Installerait NetBird et rejoindrait le mesh avec SETUP_KEY"
  fi
fi

# Repli sur l'IP locale si pas encore dans le mesh
if [ -z "$IP_MESH" ]; then
  # Essai d'interface wt0 (NetBird) puis ip route, sinon hostname -I
  IP_MESH=$(ip addr show wt0 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -1 || true)
  if [ -z "$IP_MESH" ]; then
    IP_MESH=$(hostname -I 2>/dev/null | awk '{print $1}' || hostname -i 2>/dev/null | awk '{print $1}' || true)
  fi
  _wr "Pas de mesh détecté — utilisation de l'IP $IP_MESH (visible depuis le serveur ?)"
fi

if [ -z "$IP_MESH" ]; then
  _ko "Impossible de déterminer l'IP de cette machine. Passez SETUP_KEY ou rejoignez le mesh manuellement."
  exit 1
fi

# ── Étape 2 : détecter un runtime LLM existant ───────────────────────────────
LLM_PORT=""
LLM_MODELE_ACTIF=""

# Ollama (:11434)
if curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  LLM_PORT=11434
  LLM_MODELE_ACTIF=$(curl -sf "http://127.0.0.1:11434/api/tags" 2>/dev/null \
    | grep -oE '"name":"[^"]*"' | head -1 | sed 's/"name":"//;s/"//' || true)
  _ok "Ollama détecté sur :11434 (modèle actif : ${LLM_MODELE_ACTIF:-aucun})"
fi

# LM Studio (:1234)
if [ -z "$LLM_PORT" ] && curl -sf "http://127.0.0.1:1234/v1/models" >/dev/null 2>&1; then
  LLM_PORT=1234
  LLM_MODELE_ACTIF=$(curl -sf "http://127.0.0.1:1234/v1/models" 2>/dev/null \
    | grep -oE '"id":"[^"]*"' | head -1 | sed 's/"id":"//;s/"//' || true)
  _ok "LM Studio détecté sur :1234 (modèle : ${LLM_MODELE_ACTIF:-aucun})"
fi

# llama.cpp server (:8080)
if [ -z "$LLM_PORT" ] && curl -sf "http://127.0.0.1:8080/v1/models" >/dev/null 2>&1; then
  LLM_PORT=8080
  _ok "llama.cpp server détecté sur :8080"
fi

# ── Étape 3 : installer Ollama si aucun runtime ──────────────────────────────
if [ -z "$LLM_PORT" ]; then
  _inf "Aucun runtime LLM détecté — installation d'Ollama..."

  # Choisir le modèle par RAM disponible (override : MUSCLE_MODELE)
  if [ -n "$MUSCLE_MODELE" ]; then
    MODELE_CHOISI="$MUSCLE_MODELE"
  else
    RAM_BYTES=0
    # macOS
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    if [ "$RAM_BYTES" = "0" ]; then
      # Linux
      RAM_BYTES=$(awk '/MemTotal/{print $2*1024}' /proc/meminfo 2>/dev/null || echo 0)
    fi
    RAM_GB=$(( RAM_BYTES / 1073741824 ))
    _inf "RAM détectée : ${RAM_GB} Go"

    if [ "$RAM_GB" -ge 64 ]; then
      MODELE_CHOISI="llama3.3:70b-instruct-q4_K_M"
    elif [ "$RAM_GB" -ge 28 ]; then
      MODELE_CHOISI="qwen2.5:14b"
    elif [ "$RAM_GB" -ge 14 ]; then
      MODELE_CHOISI="llama3.1:8b"
    else
      MODELE_CHOISI="qwen2.5:3b"
    fi
    _inf "Modèle choisi : $MODELE_CHOISI (${RAM_GB} Go RAM)"
  fi

  LLM_PORT=11434
  LLM_MODELE_ACTIF="$MODELE_CHOISI"

  if [ -z "$MUSCLE_DRYRUN" ]; then
    # Installer Ollama
    curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1
    # Démarrer le service (écoute sur toutes les interfaces pour que le mesh atteigne le port)
    OLLAMA_HOST="0.0.0.0:11434" ollama serve >/dev/null 2>&1 &
    sleep 2
    # Télécharger le modèle choisi
    _inf "Téléchargement de $MODELE_CHOISI (peut prendre plusieurs minutes)..."
    ollama pull "$MODELE_CHOISI"
    _ok "Ollama installé, modèle $MODELE_CHOISI prêt"
  else
    _inf "[DRY-RUN] Installerait Ollama, téléchargerait $MODELE_CHOISI"
  fi
fi

LLM_ENDPOINT="http://${IP_MESH}:${LLM_PORT}"
MODELE_FINAL="${MUSCLE_MODELE:-$LLM_MODELE_ACTIF}"

# ── Étape 4 : construire le payload et s'inscrire ────────────────────────────
PAYLOAD="{
  \"id\": \"$MUSCLE_ID\",
  \"nom\": \"$(hostname)\",
  \"endpoint\": \"$LLM_ENDPOINT\",
  \"modele\": \"$MODELE_FINAL\",
  \"methode_reveil\": [\"wakeping\"],
  \"priorite\": 50
}"

_inf "Payload d'inscription :"
echo "$PAYLOAD"
echo ""

if [ -n "$MUSCLE_DRYRUN" ]; then
  _inf "[DRY-RUN] S'inscrirait auprès de https://$CALCUL_MESH/noeuds avec X-API-Key"
  _ok "Dry-run terminé — aucune installation ni inscription effectuée."
  exit 0
fi

_inf "Inscription auprès de https://$CALCUL_MESH/noeuds ..."
HTTP_CODE=$(curl -s -o /tmp/_muscle_resp.json -w "%{http_code}" \
  -X POST "https://$CALCUL_MESH/noeuds" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MUSCLE_KEY" \
  -d "$PAYLOAD" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
  _ok "Muscle inscrit avec succès !"
  cat /tmp/_muscle_resp.json 2>/dev/null || true
  echo ""
  _ok "Ce muscle est maintenant visible dans le Cerveau de Workplace."
  _ok "Son modèle sera disponible dans LiteLLM pour le Cœur."
elif [ "$HTTP_CODE" = "422" ]; then
  _ko "Inscription refusée (422) — le serveur n'a pas pu sonder $LLM_ENDPOINT"
  _wr "Vérifiez que le service LLM est démarré et accessible depuis le réseau mesh."
  cat /tmp/_muscle_resp.json 2>/dev/null || true
  exit 1
elif [ "$HTTP_CODE" = "401" ]; then
  _ko "Clé API invalide (401) — vérifiez MUSCLE_KEY."
  exit 1
else
  _ko "Erreur inattendue (HTTP $HTTP_CODE)"
  cat /tmp/_muscle_resp.json 2>/dev/null || true
  exit 1
fi
