# S199 — Audio global veille + envoi mail, suppression mail groupée, compaction personnages — design

Trois chantiers indépendants, bundlés dans un même sprint car demandés ensemble et
tous de taille réduite.

## But

1. Pouvoir générer un audio unique concaténant plusieurs digests de veille (dans un
   ordre choisi, avec interludes parlés) et l'envoyer par email.
2. Pouvoir supprimer des mails depuis l'UI de la brique Mail — action absente
   aujourd'hui alors que le backend la supporte déjà.
3. Rendre la liste des personnages enregistrés (fiches) navigable quand elle devient
   longue, dans l'écran « personnage holistique ».

## Contexte technique constaté

- **Veille** (`briques/veille-info`, port 6120) : l'audio existe déjà **par digest**
  (table `digest_audio`, fonction `_generer_audio` dans `digest.py:56`) — appelle la
  brique voix. Aucune notion d'« audio global » multi-thématiques n'existe (ni table,
  ni endpoint) ; le manifest affirme encore à tort qu'aucune génération audio n'existe.
- **Mail** (`briques/mail`, port 6030) : le backend a déjà `mail_supprimer`
  (`DELETE /mail/{message_id}`), `mail_deplacer`, `mail_marquer_lu`. Sur un vrai compte
  IMAP, ces trois actions **agissent réellement sur le serveur** (`fournisseurs.py`) :
  `mail_supprimer` tente un `UID MOVE` vers `\Trash` et, si aucune corbeille n'est
  détectable, fait un `STORE \Deleted` + `expunge()` **définitif**. Le front (page HTML
  unique servie par `main.py:646`) n'a aucun bouton pour ces actions et affiche même
  « Lecture seule : rien n'est jamais supprimé ni déplacé » — un bandeau qui décrit
  l'absence de bouton, pas une garantie serveur. Ces actions sont gardées par
  `confirme=true` côté Cœur, mais le front mail est embarqué en `<iframe>`
  (`core/routers/dashboard.py:863`) et ne passe pas par ce chemin.
- **Mail — pièces jointes** : non supportées. `envoi.py` construit l'email avec
  `set_content()`/`add_alternative()` uniquement (texte/HTML), aucun `add_attachment()`.
  Construire ce support serait un chantier à part entière.
- **Transferts** (`briques/transferts`) : a déjà le pattern « lien signé à expiration »
  (`stockage.py` : `creer_transfert(proprietaire, expiration_heures)`, jetons
  `secrets.token_urlsafe`, statut `expire` recalculé). Réutilisable tel quel.
- **Personnages** (`briques/personnages`, port 5900) : les fiches ont déjà des
  **catégories** (sprint « Personnages catégories v0.8.0 »). L'écran holistique
  (`front_holistique.html`) liste les fiches sans groupement ni recherche.

## Section 1 — Audio global veille + envoi email

### Architecture

```
veille-info (6120)
  POST /audio-global/generer {ordre_thematiques: [digest_id...]}
    → pour chaque digest, si digest_audio absent : erreur (pas de génération à la volée)
    → synthèse TTS d'un interlude par thématique ("Voici les nouvelles pour la veille
      <nom_thematique>"), via briques/voix (même pattern que _generer_audio)
    → concaténation ffmpeg : interlude₁ + digest_audio₁ + interlude₂ + digest_audio₂ + …
    → stocke dans veille_audio_global, retourne audio_id

  POST /audio-global/{audio_id}/envoyer {destinataires: [...], sujet?, message?}
    → upload du fichier vers briques/transferts (expiration 7j) → lien signé
    → briques/mail : mail_composer (dictée = message + lien) → mail_brouillon_envoyer
    → journalise l'envoi

  POST /audio-global/generer-et-envoyer {ordre_thematiques, destinataires, sujet?, message?}
    → enchaîne les deux, best-effort (si l'envoi échoue, l'audio généré reste disponible)
```

### Schéma DB (`briques/veille-info/stockage.py`)

```sql
CREATE TABLE veille_audio_global (
  id UUID PRIMARY KEY,
  cle_api TEXT NOT NULL,          -- isolation multi-tenant (cohérent avec fiches/distributions)
  date DATE NOT NULL,
  ordre_thematiques UUID[],       -- digest_id, dans l'ordre choisi
  fichier_audio_url TEXT,         -- chemin local, servi par veille-info
  duree_secondes INT,
  statut TEXT DEFAULT 'pret',     -- pret / erreur
  cree_le TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE veille_audio_global_envois (
  id UUID PRIMARY KEY,
  audio_global_id UUID REFERENCES veille_audio_global(id),
  destinataire TEXT NOT NULL,
  statut TEXT NOT NULL,           -- envoye / echec
  message_id TEXT,                -- id renvoyé par mail_brouillon_envoyer
  envoye_le TIMESTAMPTZ DEFAULT NOW()
);
```

### Outils (manifest `briques/veille-info/manifest.json`)

- `veille_audio_global_generer(ordre_thematiques: [digest_id])`
- `veille_audio_global_envoyer(audio_id, destinataires[], sujet?, message?)`
- `veille_audio_global_generer_et_envoyer(ordre_thematiques[], destinataires[], sujet?, message?)`

### Permissions

Destinataires limités aux membres du workspace courant (même mécanisme d'isolation
`cle_api`/session que le reste de la brique, cf. S182/S183 isolation multi-utilisateur)
— pas de liste d'adresses pré-approuvées séparée, YAGNI tant qu'un besoin externe
n'est pas exprimé.

### UI (`atelier-veille`, onglet « Audio global »)

- Sélecteur de thématiques + réordonnancement (drag ou flèches haut/bas)
- Bouton « Générer l'audio »
- Lecteur audio une fois prêt
- Bouton « Envoyer par email » → modal (destinataires multi, sujet, message)
- Historique des envois (date, destinataires, statut) — lit `veille_audio_global_envois`

### Gestion des erreurs

- Digest sans audio dans `ordre_thematiques` → erreur explicite avant de lancer la
  concaténation (pas de génération à la volée qui masquerait un digest manquant).
- Échec d'un envoi à un destinataire (mail invalide, etc.) → n'empêche pas les autres,
  chaque destinataire a son propre statut dans `veille_audio_global_envois`.
- Échec de l'upload vers `transferts` → l'audio généré reste consultable/téléchargeable
  depuis l'UI même si l'envoi mail échoue.

## Section 2 — Suppression mail groupée

### Architecture

```
Front mail (main.py, page HTML embarquée)
  checkbox par ligne + "tout sélectionner"
  barre d'action "Supprimer la sélection (N)" (visible si N ≥ 1)
    → confirm() JS obligatoire, texte explicite (irréversible sur compte réel)
    → POST /mail/supprimer-lot {message_ids: [...]}

briques/mail/main.py
  POST /mail/supprimer-lot
    → boucle sur la logique existante de `supprimer` (main.py:355) pour chaque id
    → renvoie {resultats: [{message_id, ok, erreur?}, ...]}
```

### UI

- Colonne checkbox ajoutée à la liste des mails.
- Barre d'action flottante en bas/haut de liste, n'apparaît qu'avec une sélection non
  vide.
- Après la confirmation, affichage du résultat par mail si échec partiel (ex. « 3/5
  supprimés, 2 échecs » avec le détail).
- Pas de bouton de suppression individuelle par mail (hors périmètre, décision
  explicite) — uniquement l'action groupée.

### Gestion des erreurs

- Échec partiel (ex. un message déjà supprimé côté serveur, erreur réseau IMAP) :
  les autres suppressions de la sélection continuent, le résultat détaillé est
  affiché, rien n'est mis sous le tapis.
- Le bandeau front existant (« lecture seule ») est retiré/mis à jour puisqu'il devient
  faux dès l'ajout de ce bouton.

## Section 3 — Compaction de la liste des personnages enregistrés

### UI (`briques/personnages/front_holistique.html`)

- Fiches groupées en **accordéon par catégorie** (catégorie déjà existante en base
  depuis le sprint v0.8.0), replié par défaut.
- Barre de recherche/filtre texte en haut (nom de scène), qui déplie automatiquement
  les catégories contenant un résultat.
- Bouton « tout déplier / tout replier ».
- Aucun changement backend : la donnée (catégorie par fiche) existe déjà, c'est
  purement un regroupement côté front.

### Gestion des erreurs

- Fiches sans catégorie assignée → groupées sous une catégorie « Autres », toujours
  visibles (pas de perte silencieuse de personnages non catégorisés).

## Test

- **Section 1** : générer un audio global sur 2-3 digests ayant déjà `digest_audio`,
  vérifier l'ordre et la présence des interludes à l'écoute ; envoyer à une adresse
  test, vérifier réception du lien (expire après 7j) ; vérifier qu'un digest sans
  audio bloque proprement la génération.
- **Section 2** : sélectionner plusieurs mails sur un compte mock, vérifier la
  confirmation bloquante, vérifier le résultat par mail ; tester un cas d'échec
  partiel simulé.
- **Section 3** : avec un nombre de fiches suffisant pour couvrir plusieurs
  catégories, vérifier le repli par défaut, la recherche, et le cas fiche sans
  catégorie.

## Hors périmètre (explicitement)

- Pièces jointes email natives (MIME) — remplacé par lien signé via `transferts`,
  cohérent avec l'absence totale de ce support dans la brique Mail aujourd'hui.
- Suppression mail individuelle bouton par bouton — uniquement l'action groupée.
- Purge définitive de la corbeille / vidage — non demandé, hors périmètre.
- Fusion/agrégation réelle de plusieurs personnages en un « personnage combiné » —
  ce besoin, s'il existe un jour, passe par le mécanisme distinct des
  distributions/castings déjà en place, pas par ce chantier de compaction UI.
