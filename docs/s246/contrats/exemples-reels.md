# Exemples de réponses réelles Dokploy v0.31.4 (lecture seule, 2026-11-25, identifiants masqués)

## GET /api/project.all
Les applications n'y portent que 3 champs (pas d'`appName`).
```json
[{"projectId":"…","name":"temoin","description":"…","createdAt":"…","organizationId":"…","env":"…",
  "environments":[{"name":"production","environmentId":"…","isDefault":true,
    "applications":[{"applicationId":"…","name":"calendrier-familial","applicationStatus":"done"}],
    "mariadb":[],"mongo":[],"mysql":[],"postgres":[],"redis":[],"compose":[],"libsql":[]}],
  "projectTags":[]}]
```

## GET /api/application.one?applicationId=…
~150 champs dont `appName` ("calendrier-familial-sq5rzh"), `applicationStatus`, `rollbackActive`,
`refreshToken`, `env`, `password` (à ne jamais relayer). `deployments[]` est trié du plus ancien au
plus récent ; chaque entrée : `deploymentId, title, description, status, logPath, createdAt,
startedAt, finishedAt, errorMessage, rollbackId, …`. `rollbackId` vaut `null` pour les déploiements
antérieurs à l'activation du rollback/registre, une chaîne ensuite.

## GET /api/deployment.readLogs?deploymentId=…&tail=N
Paramètre `tail` (défaut 100, max 10000) ; la réponse est une chaîne JSON (le journal de build brut,
~9 Ko pour un build complet) à masquer avant toute sortie.
