# Sprint S25 — Oria, refonte visuelle (incrément 2)

> **Statut** : ✅ **CODE LIVRÉ + PROUVÉ OFFLINE + PROUVÉ LIVE + DETTES SOLDÉES** (2026-06-09)
> — persistance backend (4 tests verts), build frontend OK (1588 modules), bout-en-bout
> rejoué sur la stack Docker (frontend 3003, backend 8000, realm oria, compte `s19test`).

## Objectif

Suite de l'incrément 1 (design system « dark chaud & or » : tokens + moteur de thème +
éditeur Apparence, livré et vérifié live le 2026-06-08). Cet incrément 2 traite les
finitions identifiées et, surtout, **fait vivre le thème côté serveur** au lieu du seul
`localStorage`.

## Périmètre & ce qui a été livré

### 1. Persistance backend du thème — **par utilisateur** (cœur du sprint)
Avant : le thème ne vivait qu'en `localStorage` → perdu au changement d'appareil/navigateur.

- **`models/user.py`** : nouvelle colonne `theme` (`Text`, JSON sérialisé
  `{accent, surface, text, tint}`, vide = défaut front).
- **`main.py`** : migration douce `ALTER TABLE users ADD COLUMN theme TEXT DEFAULT ''`
  (même motif que les migrations S115/S72).
- **`routers/auth.py`** :
  - `GET /auth/me` expose désormais `user.theme` (objet ou `null`).
  - `PATCH /auth/me` accepte `theme` et le **sanitise côté serveur** avant persistance
    (`_sanitize_theme`) : seules les clés connues sont gardées, `accent/surface/text`
    doivent matcher `^#[0-9a-f]{3,8}$`, `tint` est borné `[0..100]`, les clés inconnues
    sont ignorées (anti-injection). `update_profile` ignorant les `None`, envoyer un
    thème seul **n'écrase pas** nom/emoji/bio (update partiel).
- **Frontend** :
  - `theme/theme.js` : `hydrateRemoteTheme(remote)` (applique + met à jour le cache local)
    et `pushRemoteTheme(theme)` (PATCH débouncé 600 ms → pas de spam pendant un drag).
  - `hooks/useAuth.jsx` : au login, le thème serveur renvoyé par `/auth/me` **prime** sur
    le cache local (`hydrateRemoteTheme`).
  - `components/AppearanceSettings.jsx` : chaque réglage (`persist`, `applyProfile`)
    pousse vers le backend en plus du cache local.

### 2. Ambiance **par monde** (`World.couleur`)
Un monde porte sa couleur comme accent **pour tous ses membres**, le temps qu'on y est.

- `theme/theme.js` : `applyWorldAmbiance(couleur)` / `clearWorldAmbiance()` — override
  **éphémère** de `--accent` (ne touche ni `localStorage` ni backend ; le thème perso
  reste la base).
- `components/MainLayout.jsx` : effet sur `worldActif?.couleur` → applique à l'entrée,
  restaure le thème perso à la sortie (cleanup au démontage).
- **L'ambiance ne s'applique qu'aux mondes à couleur DÉLIBÉRÉE.** Les couleurs par défaut
  héritées d'avant la refonte — `#5865F2` (défaut du modèle `World`) **et `#2D5A27`** (vert
  posé par l'onboarding dans `auth_service`) — sont **ignorées** (`_LEGACY_DEFAULTS`).
  Sinon, le monde par défaut « Mon espace » (vert `#2D5A27`) masquait l'accent perso de
  l'utilisateur → on avait l'impression que **changer son thème ne faisait rien**. Bug d'UX
  repéré par l'utilisateur à la revue live et corrigé séance tenante (cf. preuve LIVE n°5).

### 3. Typo d'affichage — serif **Fraunces** sur les titres de lieux
`styles/global.css` : `--f-display` (Fraunces) étendu aux **noms de mondes** (`.world-header-nom`),
**de salons** (`.channel-panel-nom`) et **de rooms** (`.room-header-info`). Les badges
secondaires (building/world) restent en grotesque `--f-ui` pour la lisibilité.

## Décisions actées (honnêteté technique)

- **Long-tail couleurs : assumé comme palettes intentionnelles, pas écrasé.** Les hex
  résiduels (violets agents, bleus info, palette votes/coins, `#fff` de contraste) portent
  une **sémantique de feature** ; un mapping aveugle vers l'accent unique les aurait
  effacées et aurait été non vérifiable. Décision : on les garde tels quels. Un mapping
  fin *par feature* reste une évolution possible (faible valeur, fort risque).
- **Persistance = (a) par utilisateur livrée, (b) par monde livrée** (l'énoncé disait
  « et/ou » — les deux sont faites).

## Preuve offline
- **Backend** : `tests/test_auth.py` — **11/11 verts**, dont 4 nouveaux S25 :
  `theme_absent_par_defaut`, `patch_me_persiste_theme` (relecture indépendante = bien en base),
  `patch_me_sanitize_theme_invalide` (hex invalide écarté, tint borné, clé inconnue ignorée),
  `patch_me_theme_ne_casse_pas_le_reste` (update partiel).
  (Lancé dans un venv jetable Python 3.14 + PYTHONPATH vers `workspace/shared` ;
  `onnxruntime` du `requirements.txt` n'installe pas sur 3.14 mais n'est pas requis pour `auth`.)
- **Frontend** : `npm run build` (Vite 5) — **1588 modules transformés, build OK**,
  mes 5 fichiers compris.

## Preuve LIVE (bout-en-bout, stack Docker réelle — 2026-06-09)
Backend `oria-backend-1` redémarré pour appliquer la migration (volume `./backend:/app`,
pas de `--reload`) ; colonne `theme` confirmée dans le **Postgres réel** (`oria-db-1`).
Login Playwright `s19test` sur le frontend Vite (3003) via SSO Keycloak realm oria :

1. **Persistance par utilisateur** — dans Réglages → Apparence, accent passé à `#e26965`.
   `localStorage` mis à jour **et** la base montre
   `theme = {"accent":"#e26965","surface":"#d49a36","text":"#f1ece3","tint":16}` → le
   round-trip UI → `PATCH /auth/me` → DB est réel.
2. **Survit à l'effacement du cache** — `localStorage` **entièrement vidé** puis reload :
   il est **repeuplé depuis le backend** (`/auth/me` → `hydrateRemoteTheme`) avec le même
   `#e26965`. Le thème vit donc bien côté serveur, pas juste en local.
3. **Ambiance par monde** — `--accent` rendu = `#2d5a27`, exactement la `couleur` du monde
   « Mon Jardin Secret » en base, qui **surcharge** l'accent perso `#e26965` tant qu'on est
   dans le monde (override éphémère).
4. **Fraunces** — le titre `.channel-panel-nom` (« Mon Jardin Secret ») est rendu en
   `font-family: Fraunces, Georgia, serif` (computed style live).
5. **Correctif d'ambiance vérifié** — après ajout des défauts hérités à `_LEGACY_DEFAULTS`,
   relog : `--accent` affiché = **`#e26965`** (l'accent perso, plus le vert du monde). Le
   bouton « + Nouvel agent », le spinner et les liserés sont bien corail → le thème perso
   est désormais **visible**. Capture : `s25-live-accent-corail.png`.

Captures : `s25-live-jardin.png` (avant correctif, monde vert) et
`s25-live-accent-corail.png` (après correctif, accent perso visible) — racine projet.

## Dettes — SOLDÉES (2026-06-09)
- ✅ **Mdp `s19test` roté** via kcadm (realm oria, `oria-keycloak-1`) — l'ancien temporaire
  `Verify1234!` n'est plus valide ; nouveau mdp fort communiqué à l'utilisateur (hors doc).
- ✅ **27 `*.discord.bak` supprimés** (`git rm`) — sauvegardes de rollback de l'incrément 1,
  devenues inutiles, la refonte étant validée live.

> Voir aussi mémoires `sprint-oria-design-increment-2`, `oria-ux-a-retravailler`, et le
> chantier structurel distinct `sprint-oria-structure-navigation`.
