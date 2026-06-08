# Oria — Contexte projet pour Claude Code

## Navigation harness

→ **Features et progression :** `feature-list.json`
→ **Journal de bord :** `claude-progress.txt`
→ **Agents disponibles :** `agents/README.md`
→ **Outputs / screenshots :** `outputs/`

## Agents rapides

```
@pm dashboard              → Vue d'ensemble du projet
@dev implémente [ID]       → Implémenter une feature
@test valide [ID]          → Tester une feature avec Playwright
```

## Vue d'ensemble

**Oria** est une plateforme de communication spatiale en temps réel (type Discord mais avec une navigation spatiale). Les utilisateurs créent des **worlds** contenant des **buildings** (Maison/Site/Immeuble), eux-mêmes composés de **rooms** (texte/vocal/mixte). La voix/vidéo est gérée par **LiveKit**.

Stack : FastAPI (Python) + React 18 + Vite + LiveKit + SQLAlchemy + SQLite (dev) / PostgreSQL (prod).

## Structure

```
backend/          FastAPI app
  main.py         Point d'entrée, montage des routers
  database.py     SQLAlchemy (SQLite dev, PostgreSQL prod via DATABASE_URL)
  models/         SQLAlchemy models (user, world, building, room, dm, network…)
  routers/        Un fichier par domaine (auth, worlds, buildings, rooms, messages,
                  presence, tokens, quartiers, invitations, files, dm, network)

frontend/         React + Vite
  src/
    App.jsx       Auth state (JWT dans localStorage), routing Login/MainLayout
    main.jsx      Bootstrap React
    components/   Un composant par vue/modal
    services/
      api.js      Client API centralisé (toutes les requêtes backend passent ici)
    hooks/        Custom React hooks
    styles/
      global.css

livekit/
  livekit.yaml   Config serveur LiveKit

docker-compose.yml  Services : postgres, backend (8000), frontend (3000), livekit (7880-7882)
```

## Commandes de développement

```bash
# Backend (depuis backend/)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (depuis frontend/)
npm install
npm run dev        # Vite sur port 3000
npm run build      # Build de production

# Stack complète
docker-compose up
```

## Variables d'environnement clés

| Variable | Usage |
|---|---|
| `DATABASE_URL` | PostgreSQL prod (sinon SQLite) |
| `VITE_API_URL` | URL du backend depuis le frontend |
| `VITE_WS_URL` | WebSocket URL |
| `VITE_LIVEKIT_URL` | URL LiveKit |
| `SECRET_KEY` | JWT signing key |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Credentials LiveKit |

## Conventions

- **Backend** : Python snake_case, Pydantic pour la validation, SQLAlchemy ORM, JWT via `python-jose`
- **Frontend** : composants React en PascalCase (`.jsx`), pas de TypeScript, pas d'ESLint/Prettier configurés
- **API** : préfixe `/api/` pour toutes les routes, CORS activé globalement en dev
- **Auth** : JWT Bearer token, stocké dans `localStorage`, décodé côté client (base64)
- **Temps réel** : WebSockets pour présence/messages, LiveKit SDK pour voix/vidéo

## Modèles principaux

- `User` — email, hashed_password, avatar_emoji
- `World` — espace principal d'un utilisateur (emoji, couleur, description)
- `Member` — appartenance User↔World avec rôle (proprietaire/admin/membre)
- `Building` — conteneur de rooms (types : Maison/Site/Immeuble)
- `Room` — canal texte/vocal/mixte dans un building
- `Quartier` — district/quartier dans un world
- `Invitation` — lien d'invitation avec limite d'usage
- `DMChannel` + `DMMessage` — messages directs
