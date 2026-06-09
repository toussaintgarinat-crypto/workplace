# S26 — Structure & navigation Oria

> Pendant structurel du S25 (qui a soldé le visuel). Objectif : assainir le **moteur de
> navigation** d'Oria, le rendre **adressable** (URL), et prolonger l'**onboarding** jusqu'à
> la première pièce. Pas de TypeScript, **aucune nouvelle dépendance**.

## Contexte / problème

`MainLayout.jsx` pilotait la zone centrale avec **14 booléens `show*`** (`showMap`,
`showAgents`, `showIPCRA`, `showFeed`, `showConductor`, `showJardin`, `showNetwork`,
`showDiscovery`, `showMyDocs`, `showMembers`) **+ `outilActif`** (6 valeurs) **+** `docsScope`,
`dmDestinataire`, `voteConseil` — ~20 états mutuellement exclusifs réconciliés **à la main**
via `clearAllViews()` à chaque navigation.

- **Empilement latent** : un oubli dans `clearAllViews()` = deux vues rendues. Logique
  dupliquée dans `entrerRoom`, `ouvrirOutil`, `ouvrirVotes`, `ouvrirMembers`, `chargerWorldComplet`.
- **Navigation 100 % en mémoire** : aucun routeur → un **refresh ramenait à l'accueil**,
  **aucun lien vers une room n'était partageable**.
- **Onboarding incomplet** : `EasySetupWizard` (3 étapes) marquait `setup-complete` puis
  déposait l'utilisateur dans un `MainLayout` **sans monde** → écran nu.

## Ce qui a été livré

### Incrément 1 — Machine à états de la vue centrale
- Les 14 booléens + `outilActif` + `docsScope`/`dmDestinataire`/`voteConseil` remplacés par
  **un seul état** `vue` (`{ kind, …payload } | null`) dans `MainLayout.jsx`.
  `roomsOuvertes` reste la **couche de base** ; `vue` est l'overlay exclusif au-dessus.
- `clearAllViews()` **supprimé** → `setVue(null)`. Chaque helper pose la vue atomiquement
  (`ouvrirOutil` → `setVue({ kind:'outil', outil })`, etc.) → **empilement impossible par
  construction**. Bloc de rendu réécrit en chaîne `vue?.kind === …`.
- `WorldSidebar.jsx` : 9 props `show*` remplacées par une seule `vueActive` ; chaque bouton
  calcule son `actif` via `vueActive === 'map'` etc.
- `ChannelPanel.jsx` : signatures inchangées, recâblées côté parent vers `setVue`.

### Incrément 2 — Synchronisation URL (hook maison, 0 dépendance)
- **`frontend/src/hooks/useUrlSync.js`** (nouveau) : sérialise `worldActif`/`vue`/`roomsOuvertes`
  vers un **hash** (`#/w/<id>`, `#/w/<id>/r/<roomId>`, `#/w/<id>/map`, `#/w/<id>/outil/search`,
  `#/feed`…), parse au montage, `pushState` aux changements, écoute `popstate`.
- `MainLayout` applique la cible d'URL après `chargerWorlds` (`appliquerCible`), au lieu
  d'ouvrir bêtement le premier monde. `chargerWorldComplet` renvoie désormais les données du
  monde (pour rouvrir les rooms depuis l'URL). Le paramètre `?invite=` existant n'est pas cassé.
- Les vues à charge utile runtime non sérialisable (`dm`, `docs`, `votes`) ne sont
  volontairement pas deep-linkées : on retombe sur `#/w/<id>` (le monde reste partageable).

### Incrément 3 — Onboarding jusqu'à la première pièce
- `EasySetupWizard.jsx` : **étape 4 « Crée ton premier monde »** (emblème + nom → `POST /worlds/`).
  À la création, dépose un repère `sessionStorage('oria_onboarding')` et pointe l'URL sur le
  nouveau monde pour que `MainLayout` l'ouvre directement. Bouton « Plus tard » pour finir sans monde.
- `MainLayout` : écran d'accueil **actionnable** — quand un monde est actif sans room ouverte,
  un CTA **« ▶ Ouvrir « <pièce> » »** ouvre la première pièce dispo ; si le monde est vide,
  message guidé vers la création. En première visite (`premiereVisite`, repère consommé une
  seule fois), l'accueil devient « Bienvenue dans <monde> ! 🎉 ».

## Fichiers touchés
| Fichier | Incr. |
|---|---|
| `frontend/src/components/MainLayout.jsx` | 1, 2, 3 |
| `frontend/src/components/WorldSidebar.jsx` | 1 |
| `frontend/src/hooks/useUrlSync.js` (**nouveau**) | 2 |
| `frontend/src/components/EasySetupWizard.jsx` | 3 |

Aucun changement backend.

## Preuves

### Offline
- **`npm run build` (Vite 5)** : vert à chaque incrément — **1588 modules transformés**.
- **`pytest tests/test_auth.py`** (dans `oria-backend-1`) : **11 passed** (contrats `/auth/me`,
  `/worlds` intacts).

### LIVE (stack Docker réelle, frontend 3003, login Playwright `s19test` via SSO Keycloak realm oria — 2026-06-09)
1. **URL ↔ état** : après login, hash = `#/w/<worldId>`. Ouvrir une room → `#/w/<id>/r/<roomId>` ;
   cliquer « Carte » → `#/w/<id>/map`.
2. **Vue unique (anti-empilement)** : sur `/map`, exactement **un** bouton sidebar `actif`
   (« Carte 2D ») et **un seul** enfant dans `.main-content` (vérifié en JS live).
3. **Survie au refresh / deep-link** : **F5** (`location.reload`) sur `#/w/<id>/r/<roomId>` →
   la room **se rouvre** (multiview, 1 room, « 📔 Journal »). Capture `s26-refresh-room.png`.
4. **Précédent / suivant** : depuis `/map`, `history.back()` → retour à `/r/<roomId>` **et**
   la room se rouvre (popstate → `appliquerCible`).
5. **Onboarding** : le CTA guidé **« ▶ Ouvrir « 📔 Journal » »** est rendu sur l'écran d'accueil
   d'un monde sans room ouverte.

### Bug corrigé en cours de preuve LIVE
Les IDs Oria sont des **UUID (strings)**, pas des entiers. La première version de `parseHash`
faisait `Number(id)` → `NaN` → la cible d'URL était ignorée et on retombait sur le premier
monde (room non rouverte au refresh). Corrigé (`decodeURIComponent`, comparaison de strings) ;
reprouvé live : la room se rouvre bien après F5.

## Restes / dettes assumées
- **Étape 4 du wizard** prouvée au build, pas encore rejouée LIVE bout-en-bout (nécessite un
  compte neuf / reset `setup-complete`). Le reste de l'onboarding (CTA première pièce) est
  prouvé LIVE.
- `dm`/`docs`/`votes` non deep-linkés (choix assumé : payloads runtime non sérialisables).
- 2 erreurs console `/admin/degraded` 403 **préexistantes** (DegradedBanner, endpoint admin),
  sans rapport avec le S26.

> Voir mémoires `sprint-oria-structure-navigation`, `oria-ux-a-retravailler`,
> `sprint-oria-design-increment-2`.
