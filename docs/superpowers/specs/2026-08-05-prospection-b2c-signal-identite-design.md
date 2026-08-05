# Prospection B2C multi-métier (signal de carence → lead qualifié vendable)

## Contexte

La famille `veille` sait aujourd'hui faire de la prospection **B2B** exclusivement
(`geo` enrichit des zones en entreprises Sirene, `veille-prospection` orchestre
zone→CRM, `mail` démarche par email). L'idée déclenchante : une entreprise (ex. un
installateur photovoltaïque) pourrait vouloir identifier des **particuliers** en
carence d'un équipement/service (ex. logements sans panneaux solaires) pour un
démarchage ciblé — généralisable à d'autres métiers (isolation, fibre...).

Usage visé (double, confirmé en brainstorming) : (1) une capacité Workplace que
n'importe quel tenant peut configurer pour son métier, ET (2) un usage interne pour
**vendre des leads** à une entreprise cliente.

**Ce qui définit un « lead » vendable** — décision structurante : ce n'est PAS un
foyer identifié (adresse + carence détectée), c'est un propriétaire qui a
**répondu** au courrier (coupon/QR/téléphone). Revendre des profils identifiés sans
qu'ils aient manifesté d'intérêt s'apparente à du courtage de données personnelles
non consenti — beaucoup plus exposé RGPD qu'un lead qui a lui-même répondu. Tout le
pipeline est construit autour de cette définition : la donnée qui sort du système
vers le client final est une **réponse**, jamais une liste brute.

**Contrainte légale vérifiée** (recherche faite pendant le brainstorming, pas une
supposition) : les fichiers fonciers (MAJIC) qui portent l'identité des
propriétaires sont réservés aux collectivités/administrations/organismes de service
public — **inaccessibles à une entreprise commerciale** — et même dans les tables
plus ouvertes, les noms de personnes physiques propriétaires sont anonymisés par
défaut. Conséquence directe sur l'architecture : **aucune brique de ce projet ne
résout elle-même l'identité d'un propriétaire**. Le courrier part adressé « à
l'occupant du logement », sur la seule base de l'adresse. Un point d'extension reste
ouvert pour un futur partenaire externe qui apporterait un nom sous sa propre base
légale, mais ce n'est pas construit ici.

Le canal retenu est le **courrier postal** (pas email/SMS) : en base légale
« intérêt légitime » (RGPD art. 6.1.f), aucun consentement préalable requis pour de
la prospection postale, à condition d'informer et de permettre l'opposition —
exactement le régime déjà appliqué au démarchage email existant (S170), transposé au
postal.

## Non-objectifs (hors périmètre de cette conception)

- **Détection par imagerie aérienne** (panneaux solaires visibles ou non) : chantier
  distinct (vision par ordinateur, source d'images payante). L'architecture du
  détecteur de signal reste pluggable pour l'accueillir plus tard (même contrat que
  le fournisseur DPE ci-dessous), mais rien n'est câblé dans cette itération.
- **Combinaison de plusieurs critères de sources différentes** (ex. DPE ET absence
  de panneaux) : tant qu'un seul fournisseur de signal logement existe (DPE), il n'y
  a rien à combiner — le problème du rapprochement d'adresses entre deux sources
  différentes est réel mais **différé** jusqu'à l'ajout d'un 2e fournisseur.
- **Construction d'une source d'identité propriétaire par nous-mêmes** (scraping,
  partenariat notarial...) : fermé légalement pour une entreprise commerciale (cf.
  Contexte). Seul un point d'extension est prévu.
- **Autonomie complète de l'assistant** (décider seul de la zone/du budget sans
  repasser par l'utilisateur) : confirmé « pas tout de suite » — le gate de
  confirmation reste systématique avant toute campagne créée et avant tout envoi
  réel.
- **Paiement/facturation de la vente de leads** : la conception s'arrête à la
  production du lead qualifié dans `forge` (statut + export via l'API CRM
  existante) ; comment ça se facture à l'entreprise cliente est hors périmètre.
- **Nouveau prestataire de routage postal réel branché** : le fournisseur postal est
  un `Mock` honnête (aucun envoi réel), comme `geo` l'a fait pour Sirene — brancher
  un vrai prestataire (ex. Merci Facteur) est un sprint séparé, la bascule reste
  possible sans redesign (motif `GEO_FOURNISSEUR=reel`).

## Architecture d'ensemble

```
veille-prospection (orchestration, campagne type=b2c)
   │
   ├─▶ geo : type d'objet "logement", fournisseur DPE (adresse, jamais de nom)
   │
   ├─▶ forge CRM : import-lot logements, statut "à contacter"
   │
   └─▶ mail : démarchage POSTAL (nouveau moteur, parallèle à l'email existant)
          │
          ├─ génère un document + un token de réponse par destinataire
          ├─ gate de confirmation avant tout envoi réel (inchangé)
          └─ page publique /repondre/{token} : capture la réponse
                 │
                 └─▶ forge CRM : PATCH statut → "lead qualifié" (= vendable)

Pilotage assistant : chaque étape est un outil manifest (action:true, gate
inchangé) ; un outil de LECTURE liste les critères de signal disponibles pour que
l'assistant compose lui-même une proposition selon le métier demandé, à valider en
conversation avant création de la campagne.
```

## Backend — `geo`

### `domaine.py`

Pas de changement au modèle `geo_objects` — il est déjà générique (type + metadata
JSON, « ajouter un type = zéro migration », cf. docstring `stockage.py`). Ajout
d'une règle de fraîcheur pour le nouveau type dans `REGLES_FRAICHEUR` :

```python
REGLES_FRAICHEUR: dict[str, list[tuple[int, str]]] = {
    "entreprise": [(30, "rouge"), (90, "orange")],
    "logement": [(30, "rouge"), (90, "orange")],   # même règle, date = date du DPE
    "_defaut": [(30, "rouge"), (90, "orange")],
}
```

Nouvelle fonction de normalisation, symétrique de `normaliser_entreprise` :

```python
def normaliser_logement(brute: dict) -> dict | None:
    """Payload brut ADEME (Observatoire DPE) → objet `geo_objects` type="logement", ou
    None si inexploitable (coordonnées absentes/hors bornes). `ref_externe` = numéro
    DPE (identifiant stable ADEME) — sert l'upsert ET la dédoublonnage CRM en aval.
    metadata NE CONTIENT JAMAIS de nom de personne : adresse, commune, grade DPE,
    surface, année de construction — strictement des caractéristiques du bien."""
```

`metadata` attendu : `{"adresse": str, "commune": str, "code_postal": str,
"grade_dpe": "A".."G", "surface_m2": float | None, "annee_construction": int | None}`.

### `fournisseurs.py`

Nouvelle famille, fichier séparé `fournisseurs_logements.py` (le fichier B2B
existant n'est pas touché — zéro risque de régression sur le pipeline Sirene qui
tourne déjà) :

```python
class MockLogements:
    """Logements SIMULÉS, déterministes par zone (même motif que Mock entreprises).
    Grades DPE variés (couvre le filtre E/F/G) pour tester sans réseau."""
    nom = "mock-logements"

class DpeAdeme:
    """API ouverte ADEME (fichiers DPE, https://files.data.gouv.fr/ademe/ ou l'API
    'DPE logements existants' de data.gouv.fr) — SANS clé, bascule explicite
    `GEO_FOURNISSEUR_LOGEMENTS=reel` (même motif que GEO_FOURNISSEUR). Filtre par
    commune/code postal + grade DPE (paramètre `parametres.grades_dpe` de la zone).
    Adresse complète + géoloc dans la réponse ADEME ; AUCUN champ propriétaire dans
    le payload source — rien à filtrer côté nous, la source ne le fournit pas."""
    nom = "dpe-ademe"
```

`fournisseur_logements()` : même factory pattern que `fournisseur()`, bascule sur la
variable d'env dédiée. `peut_traiter(zone)` renvoie un message honnête si la zone
`logement` n'a ni communes ni code postal (le fournisseur DPE a besoin d'un
filtrage administratif, pas d'un point+rayon).

### `main.py` / `stockage.py`

`ZoneEntree` et `creer_zone` acceptent déjà `type` (string libre) — `"logement"`
passe sans changement de schéma. Nouveau champ optionnel sur la zone,
`parametres: dict` (JSON, ex. `{"grades_dpe": ["E","F","G"]}`), stocké dans la
colonne `naf` existante est **inapproprié** (sémantique NAF) : ajouter une colonne
dédiée par migration douce (même motif que `naf`/`communes` existants) :

```sql
ALTER TABLE geo_zones ADD COLUMN parametres TEXT   -- JSON, ex. {"grades_dpe":[...]}
```

`enrichir_lot` (route `/prospection/enrichir-lot`) route vers
`fournisseur_logements()` quand `zone["type"] == "logement"`, sinon le chemin
entreprise actuel — un seul point de branchement, le reste de la route (upsert,
journalisation, comptage) reste identique aux deux types.

## Backend — `veille-prospection`

### `stockage.py`

```sql
ALTER TABLE campagnes ADD COLUMN type TEXT NOT NULL DEFAULT 'b2b'
```

Migration douce (même motif que `geo_zones`), rétrocompatible : toutes les
campagnes existantes deviennent `type='b2b'` sans action, comportement observable
inchangé. `creer_campagne(user_id, zone_id, type="b2b")`.

### `orchestration.py`

`_executer_campagne` ne change pas de forme : `_appeler_geo` et `_appeler_forge`
fonctionnent déjà avec n'importe quel type d'objet (le contrat `prospects` renvoyé
par `geo` est déjà générique). Le seul effet du type de campagne est **en amont**,
dans la zone `geo` déjà typée `logement` — aucune branche `if campagne["type"]`
n'est nécessaire dans l'orchestration elle-même. `_pousser_memoire` reste
best-effort, inchangé.

`forge_crm_importer_lot` (voir section forge ci-dessous) doit accepter un lot sans
`email`/`entreprise` : c'est la partie qui change réellement côté `forge`, pas côté
`veille-prospection`.

**Pourquoi `campagnes.type` existe si l'orchestration ne branche dessus nulle
part** : il sert à (1) valider à la création qu'une campagne `b2c` référence bien
une zone `geo` de type `logement` (garde-fou, pas de campagne mal configurée), et
(2) permettre à l'assistant de lister « mes campagnes B2C » sans joindre `geo`.
Ni l'un ni l'autre n'est un besoin d'orchestration horaire.

**La préparation des courriers (`mail`) n'est PAS appelée par l'orchestration**,
exactement comme le démarchage email B2B existant (S169/170) : l'horloge s'arrête à
`geo` → `forge` (import en statut « à contacter »). Le passage à `mail` est une
étape séparée, déclenchée par l'assistant ou l'utilisateur, qui relit les prospects
« à contacter » depuis `forge` pour construire le corps de
`POST /demarchage-postal/preparer` — même flux que `mail_demarchage_preparer`
aujourd'hui (« depuis CRM/geo »).

## Backend — `forge` (adapter `briques/forge/main.py`)

`crm_importer_lot` (`_signatures`, `_prospect_vers_lead`) est actuellement pensé
pour des entreprises (dédoublonnage par email ou nom d'entreprise). Extension
additive, pas de réécriture :

```python
def _signatures(lead: dict) -> set[str]:
    sigs: set[str] = set()
    if lead.get("email"):
        sigs.add("email:" + _norm(lead["email"]))
    ent = lead.get("entreprise") or lead.get("nom")
    if ent:
        sigs.add("ent:" + _norm(ent))
    if lead.get("adresse"):                       # NOUVEAU : dédoublonnage logement
        sigs.add("adr:" + _norm(lead["adresse"]))
    return sigs
```

`_prospect_vers_lead` : si le prospect porte `adresse` (et pas `entreprise`), le
`nom` du lead devient `"Occupant — " + adresse` (jamais un nom de personne — cf.
Contexte), et `notes` inclut l'adresse complète + le grade DPE. Le champ `email` du
lead CRM reste vide pour ces leads (attendu : pas d'email disponible en B2C).

**Contrat requis, à vérifier/ajuster en implémentation** : la réponse de
`crm_importer_lot` doit inclure l'`id` de chaque lead créé (`crees: [{lead_id, ...}]`)
— nécessaire pour que `mail` puisse, à la réception d'une réponse, faire
`PATCH /crm/{lead_id}` avec `{"statut": "lead qualifié"}`. Si ce n'est pas déjà le
format actuel, c'est un changement de contrat à faire dans cette tâche (pas une
brique tierce à toucher : `crm_importer_lot` vit dans `briques/forge/main.py`,
sous notre contrôle).

Statut `"lead qualifié"` : une valeur de plus dans le champ `statut` déjà libre
(pas d'enum en base, `CrmLeads.statut` est une string) — aucun changement de schéma
`forge` core nécessaire. `GET /crm?statut=lead qualifié` (déjà supporté) sert
l'export vers le client final.

## Backend — `mail` (nouveau moteur postal)

### `stockage.py`

Nouvelle table, **parallèle** à `demarchage` (qui reste 100% email, inchangée) :

```sql
CREATE TABLE IF NOT EXISTS demarchage_postal (
    tenant TEXT NOT NULL, adresse TEXT NOT NULL,
    nb_contacts INTEGER NOT NULL DEFAULT 0, dernier_contact TEXT,
    opt_out INTEGER NOT NULL DEFAULT 0, cree_le TEXT NOT NULL, maj_le TEXT NOT NULL,
    PRIMARY KEY (tenant, adresse));

CREATE TABLE IF NOT EXISTS courriers (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, adresse TEXT NOT NULL,
    lead_id TEXT,                          -- lead forge à qualifier si réponse
    token TEXT NOT NULL UNIQUE,            -- utilisé dans l'URL/QR du courrier
    contenu TEXT NOT NULL,                 -- texte imprimable (personnalisé "à l'occupant")
    statut TEXT NOT NULL DEFAULT 'brouillon',   -- brouillon | envoye | repondu
    reponse_le TEXT, cree_le TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_courriers_token ON courriers(token);
```

Registre cadence/opt-out identique en logique à `demarchage` (mêmes fonctions
`_trop_recent`, même plafond `max_contacts`/`cooldown_jours`), simplement réindexé
sur `adresse` au lieu d'`email` — code dupliqué à dessein plutôt que généralisé de
force : les deux registres n'ont pas le même identifiant naturel, forcer une
abstraction commune maintenant serait prématuré (un seul cas d'usage de chaque
aujourd'hui).

### `fournisseurs_postaux.py` (nouveau, motif `geo/fournisseurs.py`)

```python
class MockRouteurPostal:
    """N'envoie RIEN réellement — journalise ce qui AURAIT été déposé. Bascule
    explicite GEO_STYLE : MAIL_ROUTEUR_POSTAL=reel pour un vrai prestataire, jamais
    de détection silencieuse."""
    nom = "mock"
```

### `main.py`

```python
class DemarchagePostalEntree(BaseModel):
    prospects: list[dict]     # [{adresse, commune?, grade_dpe?, lead_id?}]
    gabarit: str              # corps du courrier, variables {adresse}/{commune}
    expediteur: str           # identité obligatoire (même exigence LCEN/RGPD que l'email)
    cooldown_jours: int = 90  # plus long que l'email : un courrier physique coûte cher
    max_contacts: int = 2

@app.post("/demarchage-postal/preparer", status_code=201)
def demarchage_postal_preparer(corps: DemarchagePostalEntree, tenant: str = Depends(tenant_actuel)):
    """Prépare des courriers personnalisés (adresse + grade DPE, JAMAIS de nom), un
    token de réponse par destinataire. Respecte le même registre cadence/opt-out que
    l'email, réindexé par adresse. Ne dépose RIEN réellement — même gate qu'avant
    (mail_brouillon_envoyer devient l'équivalent postal : une route d'envoi séparée,
    appelée seulement après confirmation explicite)."""

@app.post("/demarchage-postal/envoyer/{courrier_id}")
def demarchage_postal_envoyer(courrier_id: str, tenant: str = Depends(tenant_actuel)):
    """Le gate : dépose RÉELLEMENT via le routeur postal configuré (Mock par défaut).
    Jamais appelé automatiquement par l'orchestration horloge."""

@app.get("/repondre/{token}")
def page_reponse(token: str):
    """Page PUBLIQUE (aucune auth — un particulier scanne un QR, pas un tenant
    Workplace). Affiche un formulaire minimal si le token existe et n'a pas déjà
    répondu, un message neutre sinon (jamais d'erreur qui révèle l'existence/l'état
    d'un token à un tiers)."""

@app.post("/repondre/{token}")
def enregistrer_reponse(token: str, corps: ReponseEntree):
    """Marque le courrier `repondu`, notifie `forge` (PATCH statut → "lead qualifié")
    si `lead_id` est présent — best-effort côté forge (même motif que
    `_pousser_memoire` : un échec forge ne fait jamais échouer la capture de la
    réponse elle-même, ré-essayable manuellement)."""
```

## Pilotage assistant

Nouvel outil de **lecture** (pas d'action, pas de gate) dans `geo` :

```python
@app.get("/logements/criteres-disponibles")
def criteres_disponibles():
    """Catalogue des critères de signal logement configurés (aujourd'hui : DPE avec
    ses grades). Décrit en langage naturel pour que l'assistant compose une
    proposition à partir d'une activité demandée, sans table figée métier→critères
    (le mapping se fait dans la conversation, pas dans le code)."""
    return {"criteres": [{"id": "dpe", "label": "Diagnostic de performance énergétique",
             "valeurs_possibles": ["A","B","C","D","E","F","G"],
             "description": "Grade énergétique du logement, source ADEME (ouverte, "
                            "gratuite). Grades E/F/G = 'passoires thermiques'."}]}
```

Nouveaux outils `action:true` (manifest `veille-prospection` + `mail`), même gate
que l'existant : créer une campagne b2c, lancer l'enrichissement, préparer les
courriers, **envoyer réellement** (gate humain explicite), lister les leads
qualifiés. Le flux conversationnel attendu (confirmé en brainstorming) :
utilisateur exprime une activité → assistant lit `/logements/criteres-disponibles`
→ propose une combinaison + demande la zone si absente → utilisateur confirme →
création de la campagne. Aucune décision autonome de zone/budget sans repasser par
l'utilisateur (non-objectif ci-dessus).

## Tests

`geo` : `normaliser_logement` (payload ADEME valide/invalide/coordonnées hors
bornes), `DpeAdeme.peut_traiter` (zone sans commune/code postal → message honnête),
`MockLogements` déterminisme (2 appels = mêmes points), migration douce
`parametres` sur une base existante.

`veille-prospection` : migration douce `type` sur base existante (défaut `b2b`),
`creer_campagne(type="b2c")`, `_executer_campagne` avec une zone `logement` (mock
geo répond des logements, vérifie que `forge` reçoit bien des `adresse` pas des
`entreprise`).

`forge` (`briques/forge/main.py`) : `_signatures` dédoublonne par adresse,
`_prospect_vers_lead` ne met jamais de nom de personne dans `nom`/`notes`,
`crm_importer_lot` renvoie les `lead_id` créés.

`mail` : registre postal (cadence/cooldown/opt-out, symétrique aux tests email
existants `test_demarchage.py`), `demarchage_postal_preparer` refuse sans
expéditeur, `page_reponse`/`enregistrer_reponse` (token valide/invalide/déjà
répondu), notification `forge` best-effort (échec forge n'empêche pas
l'enregistrement de la réponse), **aucun contenu généré ne contient de nom de
personne** (test de garde-fou dédié, dans l'esprit du test de garde-fou X-User-Id
trouvé en S193 — cette classe d'erreur mérite sa propre assertion explicite, pas
une vérification incidente).

## Limites documentées (pas des défauts, des choix assumés)

- Sans nom de propriétaire, le taux de réponse est probablement plus bas qu'un
  courrier nominatif — accepté en échange de zéro dépendance à une source de
  données fermée légalement.
- Le fournisseur DPE est le seul câblé : la vraie « synergie multi-signaux »
  évoquée en discussion n'existe pas encore techniquement, seulement
  l'architecture qui permettra de l'ajouter sans refonte.
- Le routeur postal reste `Mock` tant qu'aucun prestataire réel n'est branché :
  aucun courrier n'est physiquement envoyé par ce projet seul.
