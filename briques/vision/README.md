# Brique `vision` — OCR / lecture de documents en API (« les yeux »)

Produit autonome (port **5960**), **provider-agnostique**. Transforme un document ou une
image (PDF, photo, scan, fichier Office) en **texte**, via une **cascade** de moteurs OCR
essayés dans un **ordre de préférence**. **Repli honnête** : si aucun moteur n'est branché
ou si tous échouent, on renvoie un message qui le **dit** (`place_holder: true`) — jamais
de faux texte extrait.

## Pourquoi

Ce sont **les yeux** du Cœur (sprint **S71** de l'épopée « Organisme vivant »). L'assistant
chaîne déjà des outils ; il lui manquait de pouvoir *lire* une pièce jointe (une facture
photographiée, un PDF, un contrat scanné). La brique se déclare au registre du noyau avec
une **capacité** `vision_lire` → elle devient automatiquement un **outil du LLM** (S63/S64)
sans toucher au code du Cœur.

Miroir des briques `images` (5950) / `transcription` (5980) / `video` (5970) : même motif
provider-agnostique, même repli honnête, même autonomie (vendable seule).

## Cascade livrée

**Souverain LOCAL d'abord** (gratuit, hors-ligne), puis **hébergés** à clé en repli. Aucune
clé n'est embarquée ; un moteur sans config est ignoré et on passe au suivant.

| `backend` | Quoi | Config |
|---|---|---|
| `markitdown` | **MarkItDown** (Microsoft) : documents **nés numériques** (PDF/Office/HTML/images) → Markdown, **en local** | *(lib installée dans l'image)* |
| `tesseract` | **Tesseract** OCR **local** : reconnaît le texte d'une **image scannée** | `TESSERACT_LANG` (déf. `fra+eng`) |
| `mistral` | **Mistral OCR** (`mistral-ocr`) : haute fidélité (mise en page, tableaux, manuscrit) → Markdown | `MISTRAL_API_KEY` (`MISTRAL_OCR_MODEL`) |
| `google` | **Google Cloud Vision** (`DOCUMENT_TEXT_DETECTION`) : OCR robuste multilingue | `GOOGLE_VISION_API_KEY` (repli `GOOGLE_API_KEY`) |

L'ordre est surchargeable par `VISION_PROVIDERS` (ex. `mistral` ou `tesseract,google`).
Le kill-switch `VISION_LOCAL=0` neutralise les moteurs locaux (force la cascade hébergée).

> L'image Docker installe les moteurs **souverains** (binaire `tesseract` + `fra`/`eng`,
> `markitdown`, `pytesseract`) : la brique est **souveraine par défaut**, sans aucune clé.
> Pour une image plus mince (hébergés seuls), retirer `requirements-local.txt` et le bloc
> `apt-get` du `Dockerfile`, puis poser une clé Mistral/Google.

## API

| Route | Quoi |
|---|---|
| `GET /sante` | Moteurs connus, configurés (lib/clé), et celui qui servirait |
| `GET /fournisseurs` | Catalogue (nom + configuré) pour un choix côté UI |
| `POST /extraire` | Un fichier en **multipart** (`fichier`) → `{texte, backend, place_holder, nb_caracteres}` |
| `POST /lire` | Un fichier par **URL** ou **base64** (JSON) → idem. Surface de la capacité `vision_lire` |

Forçage d'un moteur : `?fournisseur=mistral` (`/extraire`) ou `{"fournisseur": "mistral"}`
(`/lire`). Auth BYO optionnelle : `API_KEYS` (séparées par virgule) → header `X-API-Key`.
Taille max : `VISION_MAX_OCTETS` (déf. 25 Mo).

### Exemples

```bash
# Multipart : lire une facture scannée
curl -F "fichier=@facture.pdf" http://localhost:5960/extraire

# JSON : lire un document par URL (ce que fait le Cœur via la capacité vision_lire)
curl -X POST http://localhost:5960/lire \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://exemple.org/contrat.pdf"}'
```

## Honnêteté technique

- **Jamais de faux texte** : sans moteur utilisable, `texte: ""` + `place_holder: true` +
  une `note` qui explique quoi brancher. Les erreurs par moteur sont remontées (`erreurs`).
- **Texte vide = échec** : un moteur qui ne rend rien laisse la cascade essayer le suivant.
- **Souveraineté** : par défaut, tout se passe en local ; les moteurs hébergés ne sont
  sollicités que si une clé est posée.

## Tests

`python3 -m pytest` (27 tests offline) : cascade, forçage, repli honnête, parsing des
réponses Mistral/Google (sans réseau réel), upload multipart et surface JSON.
