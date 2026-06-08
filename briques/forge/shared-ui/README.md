# @workspace/shared-ui

Composants React, hooks et utilitaires partagés entre les 3 frontends du projet :
`assistant/frontend`, `oria/frontend`, `forge/frontend`.

## Pourquoi

Avant ce paquet, `DegradedBanner.jsx` existait en 3 copies divergentes (1 par
frontend). `formatBytes`/`formatSize` était dupliqué 3×, `relativeDate` 2×.
Sprint S98 (mai 2026) extrait ces doublons pour avoir une source unique.

## Installation locale (file: deps)

Pas de pnpm workspace (lockfiles npm existants). On utilise `file:` dans les
`package.json` des frontends :

```json
{
  "dependencies": {
    "@workspace/shared-ui": "file:../../shared-ui"
  }
}
```

Puis `npm install` dans chaque frontend.

## Usage

```jsx
// Composants
import { DegradedBanner, Modal, Spinner, Button, Toast } from '@workspace/shared-ui/components';

// Hooks
import { useDebounce, useApiCall, useFormModal } from '@workspace/shared-ui/hooks';

// Utils
import { formatBytes, relativeDate, truncate } from '@workspace/shared-ui/utils';

// Ou bien (barrel global)
import { DegradedBanner, useDebounce, formatBytes } from '@workspace/shared-ui';
```

## DegradedBanner — pattern fetcher injectable

Chaque frontend a sa propre stratégie d'auth (token, baseUrl, client centralisé).
Pour éviter d'embarquer un Context dans `shared-ui`, le composant attend un
prop `fetcher` :

```jsx
// Oria (via services/api.js)
<DegradedBanner fetcher={() => api.get('/api/admin/degraded')} />

// Forge (token localStorage)
<DegradedBanner fetcher={async () => {
  const r = await fetch(`${API}/admin/degraded`, {
    headers: { Authorization: `Bearer ${localStorage.getItem('forge_token') || ''}` },
  });
  return r.ok ? r.json() : null;
}} />

// Assistant (fetch direct sur VITE_API_URL)
<DegradedBanner fetcher={async () => {
  const r = await fetch(`${API}/admin/degraded`);
  return r.ok ? r.json() : null;
}} />
```

## Garde-fous

- **Pas de design system** — extraction sans changement de style visuel
- **Pas de dépendances runtime** — uniquement `react`/`react-dom` en peer
- **Pas de Context global** — l'auth reste à chaque frontend
- **Pas de portails** — `Modal` rend inline (chaque app gère son DOM root)

## Démo

Une page statique sans bundler : `demo.html` (ouvre dans le navigateur).
Elle importe via CDN (esm.sh) pour ne pas dépendre d'un build local.
