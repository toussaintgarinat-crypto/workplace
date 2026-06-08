FROM node:20-alpine AS build
# Build context = workspace root — needed for shared-ui (file:../../shared-ui)
WORKDIR /workspace
COPY shared-ui ./shared-ui
WORKDIR /workspace/forge/frontend
COPY forge/frontend/package.json forge/frontend/package-lock.json* ./
RUN npm install
COPY forge/frontend/ ./
# Variables Vite injectées au BUILD (la SPA est statique : ces valeurs sont gelées
# dans le bundle). Défauts = posture Workplace (S19) : realm `oria`, Keycloak sur le
# port hôte 8081 (joignable par le NAVIGATEUR, pas par le réseau Docker), client public
# `oria-app` (porte le mapper `aud: forge` ajouté en S18). VITE_API_URL vide ⇒ appels
# same-origin proxy-fiés par nginx vers le core (cf. nginx.conf). Surchargeable via
# build args dans le docker-compose de la brique.
ARG VITE_API_URL=
ARG VITE_KEYCLOAK_URL=http://localhost:8081
ARG VITE_KEYCLOAK_REALM=oria
ARG VITE_KEYCLOAK_CLIENT_ID=oria-app
ENV VITE_API_URL=$VITE_API_URL \
    VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL \
    VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM \
    VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID
RUN npm run build

FROM nginx:alpine
COPY --from=build /workspace/forge/frontend/dist /usr/share/nginx/html
COPY forge/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
