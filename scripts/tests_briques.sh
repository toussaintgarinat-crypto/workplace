#!/usr/bin/env bash
# S206 — filet de test des briques, exécuté DANS un conteneur.
#
# Pourquoi pas `pytest` directement sur le poste (ce que faisait `make test-briques`) :
# 6 briques sur 38 n'avaient aucun test exécutable, et les causes n'étaient pas des bugs mais
# l'environnement — numpy/markdown/asyncpg/livekit absents, `shared/` hors du sys.path, et
# surtout des wheels épinglées qui NE COMPILENT PAS sous le Python du poste (3.14) alors
# qu'elles s'installent sans broncher sous celui des conteneurs. Chaque brique est donc testée
# sous SA version de Python, celle de son Dockerfile.
#
# Ce script distingue deux issues, ce que l'ancienne cible confondait sous
# « [ECHEC ou deps manquantes] » :
#   • ECHEC       — des tests sont rouges. C'est une régression, le script sort en 1.
#   • ENV         — l'environnement n'a pas pu être préparé (dépendance introuvable pour la
#                   plateforme). Signalé, listé en fin de rapport, mais ne fait PAS échouer :
#                   ce n'est pas le code de la brique qui est en cause.
#
# Usage :  scripts/tests_briques.sh [brique...]     (défaut : toutes celles qui ont des tests)

set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_DEFAUT="3.12"
# Socle de test commun : pytest et ses compagnons ne sont dans AUCUN requirements de
# production (à raison — ils n'ont rien à faire dans les images livrées).
SOCLE="pytest pytest-asyncio httpx"

if ! docker info >/dev/null 2>&1; then
  echo "✗ Docker ne répond pas — ce filet a besoin d'un démon Docker."
  echo "  (lance Docker Desktop, ou exécute ce script sur le HP)"
  exit 2
fi

version_python() {
  # Dernier `FROM python:X.Y` du Dockerfile (multi-stage : le dernier est celui qui exécute).
  local dockerfile="$1/Dockerfile"
  [ -f "$dockerfile" ] || { echo "$PYTHON_DEFAUT"; return; }
  local v
  v=$(grep -oE '^FROM python:[0-9]+\.[0-9]+' "$dockerfile" | tail -1 | cut -d: -f2)
  echo "${v:-$PYTHON_DEFAUT}"
}

briques=("$@")
if [ ${#briques[@]} -eq 0 ]; then
  for d in "$RACINE"/briques/*/; do
    compgen -G "$d/test_*.py" >/dev/null && briques+=("$(basename "$d")")
  done
fi

echecs=(); envs=(); ok=()

for nom in "${briques[@]}"; do
  dossier="$RACINE/briques/$nom"
  [ -d "$dossier" ] || { echo "✗ brique inconnue : $nom"; exit 2; }
  py=$(version_python "$dossier")
  echo ""
  echo "─── $nom (python $py) ──────────────────────────────────────────"

  # Certaines briques appellent des BINAIRES système que l'image python-slim n'a pas
  # (veille-info concatène de l'audio avec ffmpeg, dev exécute git). Elles les déclarent dans
  # un `.test-apt`, à l'image de ce que fait leur Dockerfile — sans quoi leurs tests échouent
  # sur un FileNotFoundError qui ne dit rien de leur code.
  apt=""
  if [ -f "$dossier/.test-apt" ]; then
    apt=$(grep -vE '^\s*#|^\s*$' "$dossier/.test-apt" | tr '\n' ' ')
    echo "  (paquets système : $apt)"
  fi

  # La RACINE est montée, pas seulement la brique : plusieurs briques importent `shared/`
  # (leur Dockerfile prend d'ailleurs la racine comme contexte de build). On se place ensuite
  # dans le dossier de la brique, et on met sur le PYTHONPATH la racine ET le `shared/` local
  # de la brique — forge et agenda embarquent leur propre paquet `agent_personnel_shared`,
  # que leur image installe mais qu'un simple `pytest` ne voit pas.
  sortie=$(docker run --rm \
    -v "$RACINE:/monorepo" -w "/monorepo/briques/$nom" \
    -e PYTHONPATH="/monorepo:/monorepo/briques/$nom/shared" \
    -e APT_PAQUETS="$apt" \
    -e VAULT_SECRET=test-secret-0123456789 -e GATEWAY_KEY=test \
    "python:$py-slim" sh -c "
      if [ -n "\$APT_PAQUETS" ]; then
        apt-get update -qq >/dev/null 2>&1 || exit 3
        apt-get install -y -qq --no-install-recommends \$APT_PAQUETS >/dev/null 2>&1 || exit 3
      fi
      pip install --quiet --disable-pip-version-check $SOCLE 2>&1 | grep -iE '^ERROR' && exit 3
      [ -f requirements.txt ] && { pip install --quiet --disable-pip-version-check -r requirements.txt 2>&1 | grep -iE '^ERROR' && exit 3; }
      [ -f requirements-dev.txt ] && { pip install --quiet --disable-pip-version-check -r requirements-dev.txt 2>&1 | grep -iE '^ERROR' && exit 3; }
      # Le code de sortie doit être celui de PYTEST, pas celui du \`tail\` qui le suit :
      # sans cette précaution le rapport annonçait « au vert » des briques dont la collecte
      # échouait — soit très exactement le défaut que ce filet est censé supprimer.
      python -m pytest -q > /tmp/pytest.out 2>&1; code=\$?
      tail -15 /tmp/pytest.out
      exit \$code
    " 2>&1)
  code=$?

  echo "$sortie"
  if [ $code -eq 3 ]; then
    echo "  → ENV : dépendance impossible à installer sous python $py (pas une régression)"
    envs+=("$nom")
  elif [ $code -ne 0 ]; then
    echo "  → ECHEC"
    echecs+=("$nom")
  else
    ok+=("$nom")
  fi
done

echo ""
echo "═══ Bilan ═══════════════════════════════════════════════════════"
echo "  ✓ ${#ok[@]} brique(s) au vert : ${ok[*]:-—}"
[ ${#envs[@]} -gt 0 ] && echo "  ⚠ ${#envs[@]} brique(s) ENV (environnement, pas le code) : ${envs[*]}"
if [ ${#echecs[@]} -gt 0 ]; then
  echo "  ✗ ${#echecs[@]} brique(s) EN ÉCHEC : ${echecs[*]}"
  exit 1
fi
echo "  Aucune régression."
