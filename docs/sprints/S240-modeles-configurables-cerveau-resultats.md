# S240 — Résultats : modèles configurables dans ⚙ Cerveau + fermeture du cerveau

Date : 2026-10-05/06. Branche `sprint/s240-modeles-configurables-cerveau`, fusionnée dans `main`
(f4e8a2f). Plan : [plan](../superpowers/plans/2026-10-05-S240-modeles-configurables-cerveau.md).

## Fonctionnel (demande utilisateur : « configurable directement dedans sans passer par le yaml »)
- ⚙ Cerveau → section **Modèles** : ajouter un modèle (fournisseur choisi dans une liste fermée +
  identifiant), testé avant d'être gardé (`perso/<fournisseur>/<id>`, en base LiteLLM), retirer les
  siens ; liste des modèles servis par origine (ajoutés / YAML / alias Forge).
- **Modèle de la Forge** : `forge/defaut` sort du YAML et vit en base ; choisi dans ⚙ Cerveau
  (défaut `mistral/small` ou un `perso/*`), re-pointage « créer puis retirer » sans coupure, restauré si
  le test échoue ; repli YAML `[gratuit/auto, gratuit/secours]` conservé ; veille du Cœur (démarrage
  + 10 min) qui le recrée. Pastille rouge « Forge servie par les gratuits » si la clé manque.
- Jamais d'`api_base` ni de clé fournis par l'utilisateur : LiteLLM v1.86.2 ne résout pas
  `os.environ/X` en base ; les modèles ajoutés partent sans `api_key` et chaque fournisseur lit sa
  variable. OpenCode Go non ajoutable par cette voie.

## Sécurité (trouvée en préparant puis en revue — défauts antérieurs à S240)
Constats vérifiés sur le HP avant correction : réglages du cerveau modifiables sans session
(LAN + mesh) ; `/assistant/chat` exécute des outils sans session ; capacité `env_exporter` qui
renvoyait tout le `.env` ; **brique dev** sans `DEV_KEY`, 5955 sur 0.0.0.0, dépôt monté en écriture et
`docker.sock` (exécution de code root sur la VM depuis le LAN/mesh) — arrêtée en urgence (décision
utilisateur) puis redéployée verrouillée.

Corrigé :
- `exiger_admin_cerveau` (session + `CERVEAU_ADMINS` + anti-CSRF Sec-Fetch-Site/Origin + JSON
  obligatoire) sur toutes les routes qui modifient le cerveau, `/sauvegarde-usb/env|lancer|restaurer`,
  `/amelioration/*`, `/curateur/*`, `/briques/reload`, `/horloge/executer` ; session sur projets,
  profil, document. **Fermé par défaut** : sans `AUTH_ENABLED=true` + `CERVEAU_ADMINS` non vide,
  refus (opt-in dev `CERVEAU_OUVERT_SANS_AUTH=1`). Test de contrat : toute route d'écriture est
  gardée ou en liste blanche commentée.
- `env_exporter` retiré ; `/mcp` fermé si `MCP_KEY` vide avec auth active ; comparaison à temps constant.
- Outils réservés à un tour de chat admin (dispatch `outils.executer`) : toute la brique dev,
  sauvegarde USB lancer/restaurer, amélioration/curateur ; le co-agent n'hérite jamais du droit et
  n'exécute que sa trousse.
- Clés écrites dans le `.env` : format strict (plus d'injection de ligne `XXX_API_BASE=`).
- XSS stockées du dashboard (couleur de projet, fil de conversation, ~100 insertions) échappées,
  validation serveur, filet statique `core/test_dashboard_xss.py` (angles morts listés en tête).
- Brique dev : garde globale sur toutes les routes (dont l'IDE SpearCode, qui n'en avait aucune),
  `DEV_KEY` vide → 503, ports en 127.0.0.1, Cœur → dev via `proxy_net`, code-server sans mot de passe
  par défaut. Uptime Kuma sonde dev par `proxy_net`.

## Tests
Cœur 957 passed ; dev 107, forge 340 (+2 skipped), gateway-sync 28 ; `tests/` 1747 passed,
104 skipped (le filet des fichiers fantômes ignore désormais les venvs `.venv*`).

## Revue
4 tours : revue finale (1 Critical hors diff + 7 Important), relecture des correctifs (2 Critical
hors diff : XSS stockée qui contournait la garde, exécution de code via le chat → brique dev ;
3 Important), relecture du 3e tour (0 Critical, 3 Important : co-agent, sauvegarde USB, fermé par
défaut), tous corrigés. Actés : CSP du dashboard (chantier séparé) ; `/assistant/chat` et les routes
de données (conversations, rappels, agenda, usine) restent sans session tant que Telegram/Mini App
n'ont pas de clé de service ; fronts proxifiés sur l'origine du Cœur (une XSS chez eux passerait la
garde d'origine).

## Incident pendant le sprint
Un sous-agent a lancé `docker compose config`, ce qui a affiché des valeurs du `.env` du Mac dans
le transcript. Par empreinte : `GATEWAY_KEY`/`LITELLM_MASTER_KEY` et `JWT_SECRET` sont identiques à
ceux du HP → à faire tourner. Les autres affichés ne valent que pour le Mac.

## Déploiement HP (2026-10-06)
Images Cœur et dev construites sur le Mac ; étiquettes `avant-s240` ; sauvegardes `~/s240-avant/`
(données du Cœur, dump gateway, `.env` racine, YAML, composes). `.env` racine : `CERVEAU_ADMINS`
(compte de l'utilisateur, confirmé), `DEV_KEY` et `DEV_IDE_PASSWORD` générés sur place, jamais
affichés. Ordre : Gateway (YAML sans `forge/defaut`) → dev → Cœur.

## Preuve LIVE
- `forge/defaut` recréé en base par la veille du Cœur (`mistral/mistral-small-latest`) ; la Forge
  répond « La capitale de l'Espagne est Madrid. » en 2,8 s, journal « servi par repli Gateway →
  gratuit/auto » (clé Mistral toujours absente).
- Sans session : `POST /assistant/config`, `/assistant/cle-fournisseur`, `/assistant/modeles`,
  `/assistant/projets`, `GET /sauvegarde-usb/env` → 401 ; `env_exporter` absent de `/capacites`.
- Brique dev : 127.0.0.1 seulement (injoignable depuis l'IP LAN), 401 sans clé, 200 depuis le Cœur
  avec sa clé ; IDE 127.0.0.1 + mot de passe.
- `/assistant/chat` sans session : toujours 200 (Telegram), outils réservés refusés hors admin.
