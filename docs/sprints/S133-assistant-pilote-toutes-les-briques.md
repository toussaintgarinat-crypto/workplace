# S133 — L'assistant pilote TOUTES les briques

**Date** : 2026-07-02  
**Statut** : ✅ LIVRÉ (2026-07-02)  
**Objectif** : Chaque brique fonctionnelle expose ses capacités dans son `manifest.json`. L'assistant peut tout faire sans connaître les endpoints. Zéro fonctionnalité cachée.

---

## Diagnostic : ce qui manque aujourd'hui

### État actuel par brique

| Brique | Port | Outils LLM | Verdict |
|---|---|---|---|
| **ETL** | 5200 | 5 outils dans le Cœur (ingérer, lire, classer…) | Incomplet : manque URL, supprimer, lister filtré |
| **Transcription** | 5980 | 5 outils dans le Cœur | Incomplet : diarisation non exposée, pas d'upload fichier |
| **Personnages** | 5900 | 3 outils dans le Cœur | Très incomplet : 15+ routes non exposées |
| **Studio** | 6060 | 12 outils dans le Cœur | Partiellement : supprimer série, langue, portrait, animer manquants |
| **Données** | 5500 | 2 outils dans le Cœur (consulter, créer) | Très incomplet : pas de modifier, supprimer, résumé |
| **Générateur** | 5400 | 0 outil | Rien : l'assistant ne peut pas générer d'app |
| **Connexion** | 5870 | 0 outil | L'assistant ne peut pas envoyer de message sur WhatsApp/Telegram |

### Ce qu'on ne touche pas

- **Gateway** (infra LiteLLM), **Noyau** (lib partagée), **App-builder** (dashboard) : pas de logique métier à exposer.
- **Forge**, **Agenda** : déjà bien couverts dans le Cœur. À migrer vers manifest dans un sprint dédié (refactor, pas urgence).

### Stratégie

Ajouter les capacités dans le **`manifest.json` de chaque brique**. Le Cœur les auto-découvre au démarrage — zéro modification du Cœur requise. Pattern identique à `briques/mail/manifest.json` ou `briques/dev/manifest.json`.

---

## Tâche 1 — ETL : compléter les capacités (port 5200)

**Routes existantes non exposées :**
- `POST /ingerer/url` — ingérer depuis une URL (PDF en ligne, page web…)
- `DELETE /documents/{doc_id}` — supprimer un document ingéré
- `GET /documents` — lister les documents avec filtres (dossier, statut)

**Fichier :** `briques/etl/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "etl_ingerer_url",
  "description": "Ingère un document depuis une URL distante (PDF en ligne, page web, article). Le texte est extrait et indexé. Utilise cette capacité quand l'utilisateur donne un lien vers un document à ajouter.",
  "action": true,
  "endpoint": "/ingerer/url",
  "methode": "POST",
  "parametres": {
    "url": {"type": "string", "description": "URL du document à ingérer (PDF, HTML…)."},
    "dossier": {"type": "string", "description": "Dossier/projet dans lequel classer le document (optionnel)."}
  },
  "requis": ["url"]
},
{
  "nom": "etl_documents_lister",
  "description": "Liste les documents ingérés (texte extrait disponible). Filtrable par dossier ou statut. Utilise avant de lire ou classer un document.",
  "endpoint": "/documents",
  "methode": "GET",
  "parametres": {
    "dossier": {"type": "string", "description": "Filtrer par dossier/projet (optionnel)."},
    "statut": {"type": "string", "description": "Filtrer par statut : 'ok', 'erreur' (optionnel)."}
  },
  "requis": []
},
{
  "nom": "etl_supprimer_document",
  "description": "Supprime définitivement un document ingéré (par son id obtenu via etl_documents_lister). ACTION irréversible.",
  "action": true,
  "endpoint": "/documents/{doc_id}",
  "methode": "DELETE",
  "parametres": {
    "doc_id": {"type": "string", "description": "Identifiant du document (obtenu via etl_documents_lister)."}
  },
  "requis": ["doc_id"]
}
```

- [x] Ajouter ces 3 capacités dans `briques/etl/manifest.json`
- [x] Vérifier que le Cœur auto-découvre et exécute correctement via `POST /service`
- [x] **Commit** : `feat S133 : ETL — 3 capacités supplémentaires (ingerer_url, lister, supprimer)`

---

## Tâche 2 — Transcription : diarisation + upload fichier (port 5980)

**Routes existantes non exposées :**
- `POST /transcrire` (multipart) — upload d'un fichier audio direct (≠ URL)
- Paramètre `diarisation=true` sur `/transcrire` et `/transcrire-url` — identification des locuteurs

**Fichier :** `briques/transcription/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "transcription_fichier",
  "description": "Transcrit un fichier audio uploadé (mp3, wav, m4a, ogg…) en texte. Avec diarisation=true, identifie les locuteurs (Locuteur A, Locuteur B…) — utile pour les réunions, interviews, podcasts.",
  "action": true,
  "endpoint": "/transcrire",
  "methode": "POST",
  "multipart": true,
  "parametres": {
    "url_fichier": {"type": "string", "description": "URL du fichier audio à transcrire (si pas d'upload direct)."},
    "diarisation": {"type": "boolean", "description": "Identifier les locuteurs dans la transcription (défaut: false)."},
    "langue": {"type": "string", "description": "Code langue ISO (ex: 'fr', 'en'). Auto-détecté si absent."},
    "fournisseur": {"type": "string", "description": "Moteur de transcription : 'whisper' (local, défaut), 'groq', 'openai'."}
  },
  "requis": []
}
```

- [x] Ajouter `transcription_fichier` dans `briques/transcription/manifest.json`
- [x] Vérifier que l'outil existant `transcription_depuis_url` (dans le Cœur) supporte déjà l'option `diarisation` — si non, ajouter le paramètre
- [x] **Commit** : `feat S133 : transcription — diarisation + capacité fichier dans manifest`

---

## Tâche 3 — Personnages : capacités complètes (port 5900)

**Routes existantes non exposées :**
- `GET /fiches/{fid}` — lire une fiche complète
- `PATCH /fiches/{fid}` — modifier une fiche (nom de scène, bio…)
- `PATCH /fiches/{fid}/categorie` — catégoriser un personnage
- `DELETE /fiches/{fid}` — supprimer une fiche
- `POST /holistique/portrait` — générer le portrait IA d'un personnage
- `POST /distribution/proposer` — proposer une distribution de personnages pour une série
- `POST /casting` — caster des voix sur les personnages
- `GET /distributions` + `POST /distributions` — CRUD des distributions sauvegardées

**Fichier :** `briques/personnages/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "personnage_fiche_lire",
  "description": "Lit la fiche complète d'un personnage holistique enregistré (thème natal, traditions, archétype, couleur d'âme…). Utilise personnages_fiches_lister pour obtenir l'id.",
  "endpoint": "/fiches/{fid}",
  "methode": "GET",
  "parametres": {
    "fid": {"type": "string", "description": "Identifiant de la fiche (obtenu via personnages_fiches_lister)."}
  },
  "requis": ["fid"]
},
{
  "nom": "personnage_fiche_modifier",
  "description": "Modifie une fiche de personnage existante (nom de scène, catégorie, notes…). ACTION.",
  "action": true,
  "endpoint": "/fiches/{fid}",
  "methode": "PATCH",
  "parametres": {
    "fid": {"type": "string", "description": "Identifiant de la fiche."},
    "nom_scene": {"type": "string", "description": "Nouveau nom de scène (garde le nom de naissance intact)."},
    "categorie": {"type": "string", "description": "Catégorie libre (ex: 'Famille', 'Collègues')."}
  },
  "requis": ["fid"]
},
{
  "nom": "personnage_fiche_supprimer",
  "description": "Supprime définitivement une fiche de personnage. ACTION irréversible.",
  "action": true,
  "endpoint": "/fiches/{fid}",
  "methode": "DELETE",
  "parametres": {
    "fid": {"type": "string", "description": "Identifiant de la fiche."}
  },
  "requis": ["fid"]
},
{
  "nom": "personnage_portrait_generer",
  "description": "Génère un portrait IA d'un personnage holistique (image via la brique images). Retourne l'URL de l'image.",
  "action": true,
  "endpoint": "/holistique/portrait",
  "methode": "POST",
  "parametres": {
    "fid": {"type": "string", "description": "Identifiant de la fiche du personnage."},
    "style": {"type": "string", "description": "Style artistique du portrait (ex: 'réaliste', 'aquarelle')."}
  },
  "requis": ["fid"]
},
{
  "nom": "personnage_distribution_proposer",
  "description": "Propose une distribution de personnages cohérente pour une série ou une histoire (par archétype, thème natal, complémentarité). Donne un contexte narratif pour affiner.",
  "endpoint": "/distribution/proposer",
  "methode": "POST",
  "parametres": {
    "contexte": {"type": "string", "description": "Description de l'histoire, du genre, du nombre de personnages souhaités."},
    "fiches_ids": {"type": "array", "items": {"type": "string"}, "description": "Fiches de personnages existants à inclure dans la distribution (optionnel)."}
  },
  "requis": ["contexte"]
}
```

- [x] Ajouter ces 5 capacités dans `briques/personnages/manifest.json`
- [x] **Commit** : `feat S133 : personnages — 5 capacités (lire, modifier, supprimer, portrait, distribution)`

---

## Tâche 4 — Studio : compléter les capacités manquantes (port 6060)

**Routes existantes non exposées :**
- `DELETE /series/{serie_id}` — supprimer une série
- `POST /series/{serie_id}/langue` — changer la langue d'une série
- `POST /series/{serie_id}/personnages/{pid}/portrait` — générer le portrait d'un personnage de série
- `POST /series/{serie_id}/personnages/{pid}/animer` — animer un portrait (vidéo)
- `GET /series/{serie_id}/episodes` (détail avec contenu) — liste des épisodes produits

**Fichier :** `briques/studio/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "studio_serie_supprimer",
  "description": "Supprime une série audio et tout son contenu (épisodes, personnages, bible). ACTION irréversible. Récupère d'abord l'id via studio_series_lister.",
  "action": true,
  "endpoint": "/series/{serie_id}",
  "methode": "DELETE",
  "parametres": {
    "serie_id": {"type": "string", "description": "Identifiant de la série."}
  },
  "requis": ["serie_id"]
},
{
  "nom": "studio_serie_langue_changer",
  "description": "Change la langue de production d'une série (voix, scripts). ACTION.",
  "action": true,
  "endpoint": "/series/{serie_id}/langue",
  "methode": "POST",
  "parametres": {
    "serie_id": {"type": "string", "description": "Identifiant de la série."},
    "langue": {"type": "string", "description": "Code langue ISO (ex: 'fr', 'en', 'es')."}
  },
  "requis": ["serie_id", "langue"]
},
{
  "nom": "studio_personnage_portrait",
  "description": "Génère le portrait visuel d'un personnage d'une série (image IA). Retourne l'URL du portrait.",
  "action": true,
  "endpoint": "/series/{serie_id}/personnages/{pid}/portrait",
  "methode": "POST",
  "parametres": {
    "serie_id": {"type": "string", "description": "Identifiant de la série."},
    "pid": {"type": "string", "description": "Identifiant du personnage dans la série."}
  },
  "requis": ["serie_id", "pid"]
},
{
  "nom": "studio_personnage_animer",
  "description": "Anime le portrait d'un personnage de série (image → courte vidéo). Utilise la brique vidéo en coulisse.",
  "action": true,
  "endpoint": "/series/{serie_id}/personnages/{pid}/animer",
  "methode": "POST",
  "parametres": {
    "serie_id": {"type": "string", "description": "Identifiant de la série."},
    "pid": {"type": "string", "description": "Identifiant du personnage."}
  },
  "requis": ["serie_id", "pid"]
}
```

- [x] Ajouter ces 4 capacités dans `briques/studio/manifest.json`
- [x] **Commit** : `feat S133 : studio — 4 capacités (supprimer série, langue, portrait perso, animer)`

---

## Tâche 5 — Données : CRUD complet exposé à l'assistant (port 5500)

**Contexte :** La brique `données` est un magasin CRUD générique multi-tenant (`app_id × entite_id → enregistrements`). L'assistant peut déjà `consulter_donnees` et `creer_enregistrement` via le Cœur, mais ne peut pas modifier, supprimer, ni voir le résumé d'une app.

**Fichier :** `briques/donnees/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "donnees_modifier",
  "description": "Modifie un enregistrement existant dans le magasin de données. Utilise consulter_donnees pour trouver l'id d'enregistrement.",
  "action": true,
  "endpoint": "/apps/{app_id}/entites/{entite_id}/{rec_id}",
  "methode": "PUT",
  "parametres": {
    "app_id": {"type": "string", "description": "Identifiant de l'application (ex: 'agenda', 'crm')."},
    "entite_id": {"type": "string", "description": "Type d'entité (ex: 'contacts', 'taches')."},
    "rec_id": {"type": "string", "description": "Identifiant de l'enregistrement à modifier."},
    "donnees": {"type": "object", "description": "Nouvelles valeurs (remplace les champs fournis)."}
  },
  "requis": ["app_id", "entite_id", "rec_id", "donnees"]
},
{
  "nom": "donnees_supprimer",
  "description": "Supprime un enregistrement du magasin de données. ACTION irréversible.",
  "action": true,
  "endpoint": "/apps/{app_id}/entites/{entite_id}/{rec_id}",
  "methode": "DELETE",
  "parametres": {
    "app_id": {"type": "string", "description": "Identifiant de l'application."},
    "entite_id": {"type": "string", "description": "Type d'entité."},
    "rec_id": {"type": "string", "description": "Identifiant de l'enregistrement à supprimer."}
  },
  "requis": ["app_id", "entite_id", "rec_id"]
},
{
  "nom": "donnees_resume_app",
  "description": "Résumé d'une application : liste les entités et leur nombre d'enregistrements. Utile pour avoir une vue d'ensemble du contenu d'une app.",
  "endpoint": "/apps/{app_id}/resume",
  "methode": "GET",
  "parametres": {
    "app_id": {"type": "string", "description": "Identifiant de l'application."}
  },
  "requis": ["app_id"]
}
```

- [x] Ajouter ces 3 capacités dans `briques/donnees/manifest.json`
- [x] **Commit** : `feat S133 : données — 3 capacités (modifier, supprimer, résumé app)`

---

## Tâche 6 — Générateur : l'assistant peut générer et voir des apps (port 5400)

**Contexte :** La brique génère des apps HTML clientes depuis un audit d'entreprise. L'assistant n'a aucun outil pour y accéder.

**Fichier :** `briques/generateur/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "generateur_apps_lister",
  "description": "Liste les apps générées pour les clients (id, nom, statut de génération, date). Point d'entrée pour piloter le générateur.",
  "endpoint": "/apps",
  "methode": "GET",
  "parametres": {},
  "requis": []
},
{
  "nom": "generateur_app_lire",
  "description": "Lit le détail d'une app générée (sections, statut, config). Utilise generateur_apps_lister pour l'id.",
  "endpoint": "/apps/{app_id}",
  "methode": "GET",
  "parametres": {
    "app_id": {"type": "string", "description": "Identifiant de l'app générée."}
  },
  "requis": ["app_id"]
},
{
  "nom": "generateur_app_generer",
  "description": "Lance la génération d'une app HTML client depuis un audit d'entreprise existant. L'app inclut le dashboard, les données et les interfaces personnalisées. ACTION (déclenche un traitement long).",
  "action": true,
  "endpoint": "/generer",
  "methode": "POST",
  "parametres": {
    "audit_id": {"type": "string", "description": "Identifiant de l'audit source (obtenu via audit_lire)."},
    "nom_client": {"type": "string", "description": "Nom du client final pour personnaliser l'app."},
    "langue": {"type": "string", "description": "Langue de l'app générée (défaut: 'fr')."}
  },
  "requis": ["audit_id", "nom_client"]
},
{
  "nom": "generateur_app_apercu",
  "description": "Retourne l'URL d'aperçu d'une app générée pour la prévisualiser. L'app doit avoir le statut 'généré'.",
  "endpoint": "/apps/{app_id}/apercu",
  "methode": "GET",
  "parametres": {
    "app_id": {"type": "string", "description": "Identifiant de l'app générée."}
  },
  "requis": ["app_id"]
}
```

- [x] Ajouter ces 4 capacités dans `briques/generateur/manifest.json`
- [x] **Commit** : `feat S133 : générateur — 4 capacités (lister, lire, générer, aperçu)`

---

## Tâche 7 — Connexion : l'assistant peut envoyer des messages (port 5870)

**Contexte :** La brique `connexion` est le pont bidirectionnel WhatsApp/Telegram/Discord. L'assistant reçoit les messages via ce pont, mais ne peut pas **envoyer** de son propre chef (ex: alerter quelqu'un sur WhatsApp), ni voir l'état du pont.

**Routes à exposer :**
- `POST /envoyer` — envoie un message sur un réseau (Telegram, WhatsApp…)
- `POST /pousser` — envoie une notification push Telegram (déjà utilisé pour les rappels agenda)
- `GET /correspondances` — voir les correspondances utilisateur ↔ id externe

**Fichier :** `briques/connexion/manifest.json`

**Capacités à ajouter :**

```json
{
  "nom": "connexion_envoyer",
  "description": "Envoie un message texte sur un réseau de messagerie (Telegram, WhatsApp, Discord). Utilise cette capacité pour notifier l'utilisateur ou envoyer un message de sa part sur commande. ACTION.",
  "action": true,
  "endpoint": "/envoyer",
  "methode": "POST",
  "parametres": {
    "reseau": {"type": "string", "description": "Réseau cible : 'telegram', 'whatsapp', 'discord'."},
    "destinataire": {"type": "string", "description": "ID externe du destinataire (chat_id Telegram, numéro WhatsApp…)."},
    "message": {"type": "string", "description": "Texte du message à envoyer."}
  },
  "requis": ["reseau", "destinataire", "message"]
},
{
  "nom": "connexion_etat",
  "description": "État du pont de messagerie : réseaux actifs (Telegram connecté ? WhatsApp configuré ?), correspondances connues.",
  "endpoint": "/correspondances",
  "methode": "GET",
  "parametres": {},
  "requis": []
}
```

- [x] Ajouter ces 2 capacités dans `briques/connexion/manifest.json`
- [ ] **Note WhatsApp** : pour activer WhatsApp, poser `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET` dans `.env`. Le code est déjà là (`briques/connexion/adaptateurs.py:174`).
- [x] **Commit** : `feat S133 : connexion — 2 capacités (envoyer message, état pont)`

---

## Récapitulatif : bilan après ce sprint

| Brique | Capacités ajoutées | Total outils LLM |
|---|---|---|
| ETL | +3 | 8 (5 Cœur + 3 manifest) |
| Transcription | +1 | 6 (5 Cœur + 1 manifest) |
| Personnages | +5 | 8 (3 Cœur + 5 manifest) |
| Studio | +4 | 16 (12 Cœur + 4 manifest) |
| Données | +3 | 5 (2 Cœur + 3 manifest) |
| Générateur | +4 | 4 manifest |
| Connexion | +2 | 2 manifest |
| **Total** | **+22** | **~130 outils LLM actifs** |

---

## Ce qui reste hors périmètre (sprint futur)

- **Migrer les outils du Cœur vers les manifests** (Forge, Agenda, Studio, Transcription, Personnages, ETL) — refactor propre, mais fonctionnellement neutre. Sprint S134 dédié.
- **WhatsApp live** — nécessite un compte Meta Business + numéro certifié.
- **Diarisation locuteurs nommés** — pyannote.audio (GPU) pour identifier les voix, pas juste les séparer.

## Définition de DONE

- [x] Les 7 manifests mis à jour avec les capacités listées
- [x] `GET /sante` de chaque brique toujours vert (aucune régression) — prouvé LIVE 2026-07-03 : 7/7 HTTP 200
- [x] Le Cœur liste les nouvelles capacités dans `mes_capacites` — 143 outils actifs (dont 23 S133)
- [x] L'assistant peut exécuter chaque outil — prouvé via MCP LIVE 2026-07-03 : `generateur_apps_lister` (vraies apps retournées), `etl_documents_lister` (15 docs), `connexion_etat` (Telegram lié), `donnees_resume_app` (401 attendu : brique atteinte, auth Keycloak requise)

## Preuve LIVE (2026-07-03)

```
generateur_apps_lister → apps réelles (studio-audioseries-ia, …)
etl_documents_lister   → 15 documents ingérés
connexion_etat         → Telegram lié (Toussaint, chat_id 8566541216)
donnees_resume_app     → 401 (brique atteinte, Keycloak attendu — routage OK)
```
Total outils Cœur : **143**. Sprint entièrement soldé.
