#!/bin/bash
#
# Lancer Workplace — démarre le Cœur, l'assistant et toutes les briques.
#
# Double-clique ce fichier (ou lance-le depuis le Terminal). Il allume Docker
# si besoin, démarre chaque brique dans le bon ordre de dépendances, attend
# qu'elles répondent, puis ouvre le tableau de bord (onglet Assistant).
#
# Honnêteté technique : on n'affiche « en ligne » que lorsque la brique répond
# vraiment à son point de santé — pas seulement quand le conteneur est lancé.

set -uo pipefail

# ── Couleurs ────────────────────────────────────────────────────────────────
BLEU='\033[1;34m'; VERT='\033[1;32m'; JAUNE='\033[1;33m'; ROUGE='\033[1;31m'; GRIS='\033[0;90m'; RAZ='\033[0m'
ok()    { echo -e "  ${VERT}✔${RAZ} $1"; }
info()  { echo -e "  ${GRIS}·${RAZ} $1"; }
warn()  { echo -e "  ${JAUNE}!${RAZ} $1"; }
err()   { echo -e "  ${ROUGE}✗${RAZ} $1"; }
titre() { echo -e "\n${BLEU}▸ $1${RAZ}"; }

# Racine = dossier de ce script, peu importe d'où on le lance.
# Workplace est désormais autonome : gateway et oria sont DANS ce dossier.
RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo -e "${BLEU}╔══════════════════════════════════════════════╗${RAZ}"
echo -e "${BLEU}║   WORKPLACE — démarrage du Cœur + briques     ║${RAZ}"
echo -e "${BLEU}╚══════════════════════════════════════════════╝${RAZ}"

# ── 1. Docker doit tourner ──────────────────────────────────────────────────
titre "Vérification de Docker"
if ! docker info >/dev/null 2>&1; then
  warn "Docker n'est pas démarré — ouverture de Docker Desktop…"
  open -a Docker 2>/dev/null
  for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    err "Docker ne répond toujours pas. Lance Docker Desktop à la main puis relance ce script."
    echo ""; read -r -p "Appuie sur Entrée pour fermer…" _; exit 1
  fi
fi
ok "Docker est prêt"

# ── 2. Définition des briques (nom | dossier | url_sante) ───────────────────
# Ordre = ordre de dépendances. La santé vide ("") signifie « pas de check, on
# se contente du up -d » (cas d'Oria, gros stack lent à démarrer).
BRIQUES=(
  "gateway|$RACINE/briques/gateway|http://localhost:4001/health"
  "memoire|$RACINE/briques/memoire|http://localhost:5600/sante"
  "forge|$RACINE/briques/forge|http://localhost:5700/sante"
  "etl|$RACINE/briques/etl|http://localhost:5200/sante"
  "donnees|$RACINE/briques/donnees|http://localhost:5500/sante"
  "audit|$RACINE/briques/audit|http://localhost:5300/sante"
  "generateur|$RACINE/briques/generateur|http://localhost:5400/sante"
  "agenda|$RACINE/briques/agenda|http://localhost:8400/health"
  # Briques médias & outils — autonomes, découvertes par le Cœur via leur manifest.
  "calcul|$RACINE/briques/calcul|http://localhost:5990/sante"
  "ecoute|$RACINE/briques/ecoute|http://localhost:5800/sante"
  "transcription|$RACINE/briques/transcription|http://localhost:5980/sante"
  "voix|$RACINE/briques/voix|http://localhost:5985/sante"
  "images|$RACINE/briques/images|http://localhost:5950/sante"
  "vision|$RACINE/briques/vision|http://localhost:5960/sante"
  "video|$RACINE/briques/video|http://localhost:5970/sante"
  "personnages|$RACINE/briques/personnages|http://localhost:5900/sante"
  "studio|$RACINE/briques/studio|http://localhost:6060/sante"
  "restaurant|$RACINE/briques/restaurant|http://localhost:6010/sante"
  "paiements|$RACINE/briques/paiements|http://localhost:6020/sante"
  "mail|$RACINE/briques/mail|http://localhost:6030/sante"
  "recherche|$RACINE/briques/recherche|http://localhost:6040/sante"
  "oria|$RACINE/oria-stack/oria|"
  "core|$RACINE/core|http://localhost:5100/health"
  # Pont messageries : APRÈS le Cœur (il appelle :5100) + transcription/voix (vocal).
  "connexion|$RACINE/briques/connexion|http://localhost:5870/sante"
)

# Attend qu'une URL réponde (HTTP < 500). Renvoie 0 si OK avant le timeout.
attendre() {
  local url="$1" max="${2:-40}"
  for i in $(seq 1 "$max"); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null)
    if [ -n "$code" ] && [ "$code" -lt 500 ] 2>/dev/null && [ "$code" != "000" ]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# ── 3. Démarrage brique par brique ──────────────────────────────────────────
ECHECS=0
for ligne in "${BRIQUES[@]}"; do
  IFS='|' read -r nom dossier sante <<< "$ligne"
  titre "Brique « $nom »"

  if [ -z "$dossier" ] || [ ! -d "$dossier" ]; then
    warn "Dossier introuvable ($dossier) — brique ignorée."
    continue
  fi
  if ! ls "$dossier"/docker-compose*.y*ml >/dev/null 2>&1; then
    warn "Pas de docker-compose dans $dossier — brique ignorée."
    continue
  fi

  info "Démarrage des conteneurs…"
  if ! ( cd "$dossier" && docker compose up -d ) >/dev/null 2>&1; then
    err "Échec du démarrage des conteneurs de « $nom »."
    ECHECS=$((ECHECS+1))
    continue
  fi

  if [ -z "$sante" ]; then
    ok "Conteneurs lancés (pas de contrôle de santé pour cette brique)."
    continue
  fi

  info "Attente de la réponse de santé…"
  if attendre "$sante" 45; then
    ok "« $nom » est ${VERT}en ligne${RAZ} ($sante)"
  else
    warn "« $nom » est lancée mais ne répond pas encore à $sante (elle finira peut-être de démarrer)."
    ECHECS=$((ECHECS+1))
  fi
done

# ── 4. Bilan + ouverture du tableau de bord ─────────────────────────────────
titre "Bilan"
if [ "$ECHECS" -eq 0 ]; then
  ok "Toutes les briques répondent."
else
  warn "$ECHECS brique(s) à surveiller — vois les messages ci-dessus."
fi

DASHBOARD="http://localhost:5100/dashboard"
echo ""
echo -e "  ${BLEU}Cœur / Assistant${RAZ} → $DASHBOARD"
echo -e "  ${GRIS}Docs API${RAZ}        → http://localhost:5100/docs"
echo -e "  ${GRIS}Messagerie Oria${RAZ}  → http://localhost:3003"
echo ""

if attendre "$DASHBOARD" 20; then
  info "Ouverture du tableau de bord dans le navigateur…"
  open "$DASHBOARD"
  ok "Workplace est prêt. Va sur l'onglet « Assistant » pour lui parler."
else
  warn "Le Cœur ne répond pas encore — réessaie d'ouvrir $DASHBOARD dans quelques secondes."
fi

echo ""
echo -e "${GRIS}  (Pour tout arrêter : double-clique « Arrêter Workplace.command »)${RAZ}"
echo ""
read -r -p "Appuie sur Entrée pour fermer cette fenêtre…" _
