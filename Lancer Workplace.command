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
  # MinIO (cible S3 locale pour Litestream/WAL-G) — APRÈS gateway/memoire, pas avant : depuis
  # la revue finale (I6), MinIO rejoint DIRECTEMENT les réseaux memoire_default/gateway_default
  # (externes) au lieu qu'eux rejoignent proxy_net — ces réseaux n'existent qu'une fois
  # gateway/memoire démarrés une première fois. Sur un déploiement neuf (réseaux jamais créés),
  # placer sauvegarde avant échouerait à « network ... declared as external, but could not be
  # found » (reproduit et documenté pendant la correction de la revue finale). L'ordre inverse
  # n'est pas gênant pour l'archivage WAL : Postgres retente son archive_command indéfiniment
  # sans planter tant que le segment n'est pas confirmé expédié.
  # Santé vide : MinIO a son propre healthcheck interne mais pas de route /sante
  # compatible avec le motif du reste du parc (revue finale whole-branch I4).
  "sauvegarde|$RACINE/outils/sauvegarde|"
  "forge|$RACINE/briques/forge|http://localhost:5700/sante"
  "ingestion|$RACINE/briques/ingestion|http://localhost:5200/sante"
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
  # audit-fichiers AVANT vision/peertube : ces briques appelantes scannent les fichiers
  # reçus via ce service (S195) — il doit déjà être up quand elles démarrent.
  "audit-fichiers|$RACINE/briques/audit-fichiers|http://localhost:6170/sante"
  "vision|$RACINE/briques/vision|http://localhost:5960/sante"
  "video|$RACINE/briques/video|http://localhost:5970/sante"
  "personnages|$RACINE/briques/personnages|http://localhost:5900/sante"
  "studio|$RACINE/briques/studio|http://localhost:6060/sante"
  "restaurant|$RACINE/briques/restaurant|http://localhost:6010/sante"
  "paiements|$RACINE/briques/paiements|http://localhost:6020/sante"
  "mail|$RACINE/briques/mail|http://localhost:6030/sante"
  "recherche|$RACINE/briques/recherche|http://localhost:6040/sante"
  "telephonie|$RACINE/briques/telephonie|http://localhost:6050/sante"
  "synopsis|$RACINE/briques/synopsis|http://localhost:6090/sante"
  "peertube|$RACINE/briques/peertube|http://localhost:6100/sante"
  "geo|$RACINE/briques/geo|http://localhost:6110/sante"
  "atelier-veille|$RACINE/briques/atelier-veille|http://localhost:6130/sante"
  "export|$RACINE/briques/export|http://localhost:6150/sante"
  "transferts|$RACINE/briques/transferts|http://localhost:6180/sante"
  "connecteurs|$RACINE/briques/connecteurs|http://localhost:6200/sante"
  "jeu-factions|$RACINE/briques/jeu-factions|http://localhost:6210/sante"
  # Atelier dev : code/améliore les briques depuis l'assistant. Avant le Cœur
  # pour qu'il la découvre via son manifest au démarrage.
  "dev|$RACINE/briques/dev|http://localhost:5955/sante"
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
  # On CAPTURE la sortie (au lieu de l'avaler vers /dev/null) : si une image a été
  # supprimée (prune) et que sa reconstruction échoue, l'erreur reste visible —
  # sinon la panne est silencieuse et noyée parmi les ~40 briques (cas vécu :
  # transcription 5980, image fauchée par un prune, vocal cassé sans message).
  # --env-file racine en premier (fournit les secrets partagés) PUIS le .env local de la
  # brique s'il existe (en dernier, donc prioritaire sur les clés en commun — Docker
  # Compose applique les --env-file dans l'ordre, le dernier gagnant sur les clés
  # partagées, cf. Task 4 sauvegarde). Sans le .env local en second, une brique dont
  # le volume a été initialisé avec un mot de passe défini UNIQUEMENT dans son .env
  # local (ex. memoire : MEMOIRE_DB_PASSWORD) retomberait sur la valeur par défaut du
  # docker-compose.yml et échouerait l'authentification (vécu : memoire-backend et
  # gateway cassés en test avec --env-file racine seul, faute du .env local en second).
  # ⚠ Depuis la revue finale whole-branch (C1, .superpowers/sdd/progress.md), --env-file
  # N'EST PLUS la seule ligne de défense pour WAL-G/SAUVEGARDE_S3_* : ces variables sont
  # passées en `env_file:` DANS les docker-compose.yml de memoire/gateway (lu par Docker
  # Compose quelle que soit l'invocation, avec ou sans --env-file — donc ça marche
  # identiquement sur le HP où la procédure fait des `docker compose up -d` nus). Ce
  # --env-file reste utile pour les composes qui interpolent encore ${...} directement
  # (ex. MinIO, Task 1) et pour MEMOIRE_DB_PASSWORD/GATEWAY_DB_PASSWORD ci-dessus.
  env_args=(--env-file "$RACINE/.env")
  [ -f "$dossier/.env" ] && env_args+=(--env-file "$dossier/.env")
  sortie=$( cd "$dossier" && docker compose "${env_args[@]}" up -d 2>&1 )
  if [ $? -ne 0 ]; then
    err "Échec du démarrage des conteneurs de « $nom » :"
    echo "$sortie" | tail -15 | sed 's/^/      /'
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
