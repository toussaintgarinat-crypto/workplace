# S186 — Isolation par personne de la brique `memoire` (souvenirs)

Date : 2026-07-19 · Mémoire : [[sprint-s184-s187-isolation-briques-restantes]]
Suite de S184 (ecoute, mergé) et S185 (mail, commit `0d0898e`). Traite le 3ᵉ des 4 trous
reportés par l'audit S183 (`docs/rapport-s183-audit-isolation.md`) — le plus sensible : donnée
la plus personnelle (souvenirs), **aucune authentification aujourd'hui**.

## Constat (audit S183 + exploration kickoff)

`briques/memoire/main.py` (adaptateur FastAPI vers un backend externe « Memory »,
Postgres/pgvector, JWT, notion native d'« espace ») n'a **aucune vérification** sur aucune
route : `/retenir`, `/rappeler`, `/souvenirs`, `/taxonomy`, `DELETE /souvenir/{id}`, et le
proxy générique `/api/v1/{chemin:path}`. Un seul compte de service partagé porte TOUTES les
opérations. Le paramètre `espace` (optionnel, sur chaque route) n'est normalisé que pour deux
valeurs logiques (`"solution"`→`None`, `"perso"`→`"Perso"`) — **toute autre valeur est acceptée
telle quelle** comme nom d'espace Memory réel, sans aucune vérification d'identité : n'importe
quel appelant peut lire/écrire n'importe quel espace en le nommant.

Le manifest n'expose que deux espaces logiques à l'assistant (`solution`, `perso`) ; Forge et
Oria, malgré des mentions dans le docstring historique (wings IPCRa, wing_user), n'appellent
en réalité **pas** cette brique directement (ils ont leur propre intégration Memory, hors
périmètre) — aucun risque de régression de ce côté.

La tuile « Mémoire & graphe IPCRA » du dashboard (hub Créations) ouvre aujourd'hui l'UI React
brute de la brique dans un cadre, sans session ni identité — même situation que `mail` avant
S185.

Un nom d'env `MEMOIRE_KEY` existe déjà et est même **présenté** par
`core/graphe_apprentissage.py` (`Authorization: Bearer {MEMOIRE_KEY}`, pour reconstruire le
graphe d'apprentissage depuis `/souvenirs`) mais n'est **jamais vérifié** côté brique — code
mort de facto, dialecte incohérent avec `X-API-Key` retenu pour ecoute/mail.

## Décisions de kickoff (confirmées par l'utilisateur le 2026-07-19)

1. **Périmètre complet**, comme mail S185 : assistant (outils LLM) **et** tuile dashboard
   proxy-fiée — pas seulement l'assistant.
2. **Motif mail transposé** : `MEMOIRE_KEY` gage la confiance du Cœur, `X-User-Id` désigne la
   personne connectée, l'espace logique `"perso"` devient un espace Memory **par personne**
   (`Perso:{identite}`), créé à la demande. L'espace `"solution"` (« Workplace », faits sur
   l'entreprise/les projets) reste commun à tout le foyer, inchangé.
3. **Dialecte unifié `X-API-Key`** : `core/graphe_apprentissage.py` est corrigé pour envoyer
   `X-API-Key` au lieu d'`Authorization: Bearer` (la brique ne vérifiait rien avant, donc
   aucune régression possible ; sinon cet appel casserait — 401 — dès que la vérification
   devient réelle).
4. **Verrou d'espace en mode gagé** : seules `"solution"` et `"perso"` sont honorées quand
   `MEMOIRE_KEY` est présentée ; toute autre valeur d'espace fournie par l'appelant retombe
   silencieusement sur `"solution"` (l'identité vient TOUJOURS du serveur, jamais de ce que le
   client demande — motif mail). En mode ouvert (pas de `MEMOIRE_KEY` configurée), comportement
   historique inchangé — non cassant.
5. **Poussé jusqu'au bout** : un vrai sélecteur d'espace (« Commun / Personnel ») est ajouté
   dans le front React, ce qui impose de garder aussi le **proxy générique `/api/v1/*`**
   (faille trouvée en cours de conception : ce proxy relaie tout au backend avec le JWT de
   service, propriétaire de TOUS les espaces de TOUT le monde — sans garde, un sélecteur
   d'espace dans l'UI serait contournable depuis la console du navigateur en appelant
   directement `GET /api/v1/spaces` ou `/api/v1/spaces/{id_devine}/...`).

## Identité (nouveau `briques/memoire/auth.py`, motif copié de `briques/ecoute/auth.py`)

```python
def identite(x_api_key=Header(None), authorization=Header(None), x_user_id=Header(None)) -> str:
    cle = os.environ.get("MEMOIRE_KEY")
    if not cle:
        return x_user_id or "perso"          # mode ouvert, inchangé (Forge/tests/dev)
    if _presentee(x_api_key, authorization) != cle:
        raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    return x_user_id or "perso"

def gage(x_api_key=Header(None), authorization=Header(None)) -> bool:
    """True si l'appelant présente MEMOIRE_KEY (mode gagé) — utile pour décider si le verrou
    d'espace et la garde du proxy /api/v1/* s'appliquent."""
```

Pas de dialecte « tenant externe » (contrairement à mail) : l'audit S183 classe `memoire`
« personne », pas « bundle-client » — aucun tenant tiers connu à préserver.

## Normalisation d'espace (remplace `_normaliser_espace` actuel)

```python
def _normaliser_espace(espace: str | None, identite: str, gage: bool) -> str | None:
    if not espace or espace.strip().lower() == "solution":
        return None                                   # espace commun, inchangé
    if espace.strip().lower() == "perso":
        return "Perso" if identite == "perso" else f"Perso:{identite}"
    if gage:
        return None                                   # verrou : valeur libre ignorée, repli solution
    return espace                                      # mode ouvert : comportement historique
```

Point important : le repli `identite == "perso"` → nom d'espace **`"Perso"`** (pas
`"Perso:perso"`) préserve les souvenirs déjà stockés sous ce nom historique — **zéro
migration**, même logique que le défaut `proprietaire='perso'` de S184/le dialecte
`perso:{x_user_id or 'perso'}` de S185. Seules les AUTRES personnes obtiennent un espace
`Perso:{identite}` séparé.

Toutes les routes du contrat (`/retenir`, `/rappeler`, `/souvenirs`, `/taxonomy`,
`DELETE /souvenir/{id}`) gagnent `identite: str = Depends(auth.identite)` et
`gage: bool = Depends(auth.gage)`, et appellent la nouvelle `_normaliser_espace` avec ces deux
valeurs au lieu de l'ancienne fonction à un seul argument.

## Garde du proxy générique `/api/v1/{chemin:path}`

Uniquement quand `gage` est vrai (sinon passthrough inchangé, comme aujourd'hui) :

1. Résout une fois par requête `sol_id = await _espace_id(client)` (espace solution) et
   `perso_id = await _espace_id(client, "Perso" if identite == "perso" else f"Perso:{identite}")`.
2. `chemin == "spaces"` et méthode `GET` → la réponse amont est parsée et **filtrée** aux
   entrées dont l'`id` ∈ `{sol_id, perso_id}` avant d'être renvoyée (jamais la liste complète du
   compte de service).
3. `chemin` commence par `spaces/{id}` (regex simple sur le 2ᵉ segment) → si `id` ∉
   `{sol_id, perso_id}`, `404` immédiat, requête jamais transmise en amont.
4. `chemin == "spaces"` et méthode `POST` (création) → bloqué (`403`) en mode gagé : les deux
   espaces existent déjà (créés au boot par `_index_injecte`), pas de raison légitime d'en
   créer un troisième depuis le front.
5. Tout le reste sous `/api/v1/*` (`auth/*`, health…) → passthrough inchangé, aucune donnée
   cloisonnable en jeu.

## Boot du front + sélecteur d'espace

`_index_injecte()` reçoit désormais `identite` (via `spa()` → `Depends(auth.identite)`) et
calcule les DEUX ids d'espace (comme le proxy ci-dessus). Le script injecté pose :
- `localStorage.active_space_id` = `sol_id` (défaut inchangé : on atterrit sur l'espace commun,
  zéro régression visuelle) ;
- `localStorage.workplace_spaces` = `JSON.stringify({solution: sol_id, perso: perso_id})`
  (nouveau — support du sélecteur).

Nouveau petit composant front (topbar, `memory/frontend/src`) : bascule à deux positions
« Commun / Personnel » qui lit `workplace_spaces` et appelle `setActiveSpace(id)` — déjà exposé
par `useAppStore` (`briques/memoire/memory/frontend/src/stores/appStore.ts`), aucune plomberie
d'état à inventer. Nécessite un rebuild de l'image (stage Node du `Dockerfile`), comme tout
changement du front React de cette brique.

## Câblage Cœur

- `core/outils_communs.py` : `BRIQUES_PAR_PERSONNE = {"agenda", "ecoute", "mail", "memoire"}` —
  l'assistant forwarde `X-User-Id` sous `MEMOIRE_KEY` pour `memoire_retenir`, `memoire_rappeler`,
  et les autres capacités déclarées au manifest de cette brique.
- Nouveau `core/routers/memoire_proxy.py` (motif `mail_proxy.py`) : route `/memoire-app/*`,
  identité TOUJOURS dérivée de `outils_communs._entetes_brique("memoire")` (session Cœur),
  en-têtes d'identité du navigateur ignorés. Enregistré dans `core/main.py` avec
  `exiger_session` + `lire_contexte_tenant`.
- `core/routers/dashboard.py` : la tuile « Mémoire & graphe IPCRA » pointe l'iframe/cadre sur
  `/memoire-app/` au lieu de `MEMOIRE_UI_URL` brute. Le lien externe (s'il existe) reste sur
  l'URL brute — hors périmètre, comme agenda/mail.
- `.env.example` : ajoute `MEMOIRE_KEY` à côté de `AGENDA_KEY`/`ECOUTE_KEY`/`MAIL_KEY` (leçon
  S184 : sans documentation, mode ouvert silencieux au 1ᵉʳ déploiement).
- `core/graphe_apprentissage.py` : `Authorization: Bearer {memoire_key}` → `X-API-Key:
  {memoire_key}` (dialecte unifié, décision 3).

## Tests

- `briques/memoire/test_isolation_personne.py` (nouveau) : deux identités (`X-User-Id` A et B
  sous `MEMOIRE_KEY`) → espace perso de A invisible pour B (`/rappeler`, `/souvenirs`,
  `/taxonomy` scopés) ; repli `identite == "perso"` → nom d'espace legacy `"Perso"` inchangé ;
  espace `"solution"` identique pour A et B (partagé, inchangé) ; valeur d'espace arbitraire
  fournie en mode gagé → retombe sur solution ; sans `MEMOIRE_KEY` configurée → comportement
  historique (mode ouvert).
- `briques/memoire/test_proxy_api.py` (nouveau) : `GET /api/v1/spaces` filtré aux deux espaces
  autorisés ; `GET/POST /api/v1/spaces/{id}/...` avec un `id` hors allowlist → 404 ; `POST
  /api/v1/spaces` → 403 en mode gagé ; passthrough intégral en mode ouvert (régression).
- `core/test_memoire_proxy.py` (nouveau, motif `core/test_mail_proxy.py`) : identité de session
  forwardée, en-têtes navigateur ignorés.
- `core/test_contexte_tenant.py` / `core/test_outils_dynamiques.py` : `_entetes_brique("memoire")`
  forwarde `X-User-Id` comme les 3 autres briques « cercle privé ».
- `core/test_graphe_apprentissage.py` : appel sortant vérifié en `X-API-Key` (pas `Authorization`).
- `make test-core` et la suite `briques/memoire/` restent au vert.

## Hors périmètre

- Pas de migration de données réelles : espace `Perso` legacy préservé tel quel par construction
  (decision de nommage ci-dessus), pas d'`ALTER TABLE` (l'espace Memory n'est pas une table SQL
  côté brique).
- Forge (`memory_palace.py`) et Oria (`mempalace_client.py`) ont leur propre intégration directe
  au backend Memory, indépendante de cette brique — non touchés, non concernés par ce sprint.
- Pas de déploiement LIVE HP (régime [[regime-preuve-docker-differe]]) — code + tests
  uniquement.

## Risques

- Le rebuild du front React (stage Node du `Dockerfile`) est un point de fragilité connu du
  monorepo (cf. [[piege-launcher-sans-rebuild]]) — bien vérifier que l'image est reconstruite,
  pas juste redémarrée, avant toute preuve LIVE différée.
- La garde du proxy `/api/v1/*` est heuristique (parsing du chemin par segments) : à tester
  explicitement contre des variantes de chemin (`spaces`, `spaces/`, `spaces/{id}`,
  `spaces/{id}/nodes/{nid}`) pour éviter un contournement par un chemin mal anticipé.
- Généraliser `BRIQUES_PAR_PERSONNE` touche du code partagé avec agenda/ecoute/mail — mitigé
  par les tests existants de `core/test_contexte_tenant.py` qui doivent rester verts sans
  modification de leurs assertions sur les 3 autres briques.
