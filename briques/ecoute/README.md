# Brique `ecoute` — mot-clé « comme Siri » (S42) + paliers commerciaux (S43)

Détection de mot-clé vocal (**openWakeWord**, ONNX/CPU) en **flux WebSocket**.
Suite directe du POC S41 (`poc/`, décision **GO**) : ici on industrialise le moteur
prouvé en une vraie brique du registre (S42), puis on bâtit dessus **deux paliers
commerciaux** (S43).

## Paliers commerciaux (S43)

| Palier | Quoi | Mécanique |
|---|---|---|
| **Gratuit** | 4 noms d'éveil **réellement embarqués** (Hey Jarvis, Alexa, Hey Mycroft, Hey Rhasspy) | `catalogue.py` ; le client en choisit un, `GET /noms` les liste, le WS `?mot=` charge le modèle |
| **Payant** | Le **nom de marque** du client (« Maison Léon ») | `commandes.py` (cycle + idempotence) → Stripe one-off `paiement.py` (motif S21) → **file d'entraînement pilotée par l'horloge S29** `entrainement.py` → nom livré et sélectionnable |

Honnêteté assumée : openWakeWord ne livre que **4 modèles qui sont des noms d'éveil**
(pas « 5-6 » — `timer`/`weather` sont des commandes, les présenter mentirait).

Cycle d'une commande : `en_attente_paiement → payee → en_entrainement → livree` (ou `echec`).

### L'entraînement est honnête (point délicat)

Le POC S41 a établi qu'entraîner un modèle par nom demande **Piper + GPU (~1 h)**, non
embarqué ici. L'entraîneur est donc **pluggable** : `ENTRAINEUR_CMD` (vrai job GPU en
prod → `factice=False`) ; à défaut, **stand-in honnête** (copie d'un pré-entraîné sous
le nom de marque, **`factice=True`** + message explicite) qui prouve le câblage
*livraison → nom sélectionnable* sans prétendre que la marque est réellement reconnue.

### Endpoints S43

- `GET /noms` — noms gratuits + sur mesure livrés (avec `defaut`).
- `GET /paiement/etat` — config Stripe honnête (mock vs test/live, jamais la clé).
- `POST /commandes {nom_marque}` — crée (idempotent) + émet un lien de paiement.
- `GET /commandes[?statut=]`, `GET /commandes/{id}`.
- `POST /commandes/{id}/payer` — confirmation **mock** (refusée 409 si Stripe configuré : c'est le webhook qui confirme).
- `POST /paiement/webhook` — webhook Stripe **à signature vérifiée** (motif S21).
- `POST /entrainement/traiter` — **tâche de l'horloge S29** (déclarée au manifest) : avance la file + relance les impayées.

## Pourquoi une brique serveur ?

openWakeWord est **Python/ONNX, pas du JavaScript**. Le navigateur capte le micro et
**streame** l'audio ici par WebSocket — exactement comme le fait l'intégration Unmute
(`core/main.py`). Bonus marque blanche : l'audio passe par **notre infra**, plus par
Google (≠ Web Speech actuel).

## Contrat WebSocket `/ecoute`

- Le client envoie des **trames binaires** : PCM **16 kHz mono int16** little-endian
  (le flux micro brut). Les trames peuvent être de taille quelconque, même impaire :
  le détecteur recolle les fenêtres de 80 ms à travers les blocs.
- À l'ouverture, le serveur annonce `{"type":"pret","mot":...,"seuil":...}`.
- À chaque détection, le serveur renvoie `{"type":"reveil","mot":...,"score":...}`.
- Une **réfraction** (~1 s) après un réveil évite la rafale d'événements.

Le Cœur (fournisseur `creerWakeWord()`, ⚙ Cerveau → « Mot-clé ») capte alors la
commande dictée (reconnaissance navigateur) et l'envoie à `/assistant/chat` — donc le
wake word **garde toute la boucle à outils** de l'assistant.

## Santé

`GET /sante` charge réellement le modèle (un `/sante` qui ne charge rien mentirait) :
`{"statut":"ok","mot":"hey_jarvis_v0.1","seuil":0.5,"moteur":"openwakeword"}`.

## Lancer

```bash
docker compose up --build      # port 5800, image épinglée workplace/ecoute:0.2.0
# ou en local (Python 3.11 OBLIGATOIRE — pas de wheels onnxruntime en 3.14) :
python main.py
```

Le mot par défaut est le `hey_jarvis` pré-entraîné (l'assistant s'appelle « le Jarvis »).
Les modèles sur mesure livrés sont stockés dans `/data/modeles` (volume) ; commandes en
`/data/ecoute.db` (SQLite side-car, comme le journal de l'horloge).

## Tests

```bash
# Hors ligne (Python 3.11, venv du POC) :
poc/.venv/bin/python -m pytest -q        # 34 verts
#   test_detecteur (10, S42) + test_catalogue (4) + test_commandes (10)
#   + test_entrainement (6) + test_paiement (4)

# LIVE S42 — vrai service + vrai WebSocket :
#   3 positifs « hey jarvis » → 1 réveil chacun ; 7 négatifs → 0 réveil.
# LIVE S43 (mode mock) — flux palier payant complet prouvé :
#   /noms (4 gratuits) ; commande « Maison Léon » → payer (mock) →
#   POST /entrainement/traiter (la tâche de l'horloge) → livrée + relance d'une impayée ;
#   WS ?mot=alexa_v0.1 → pret ; ?mot=inconnu → erreur+close ;
#   WS ?mot=maison_leon (modèle livré) → pret + réveil sur l'audio du POC.
```

## Limite assumée (mesurée, cf. `poc/DECISION.md`)

Les modèles **pré-entraînés** sont calés sur les voix Piper et ne généralisent pas à
toute voix (`pos_alex` raté). Le produit doit **entraîner un modèle dédié par nom**
(job GPU = palier payant **S43**). Le `hey_jarvis` n'est qu'une preuve de moteur.
Le micro **navigateur** est structurellement conforme (getUserMedia → PCM 16k → trames),
prouvé ici sur fichiers à travers le vrai WebSocket.
