# Brique `ecoute` — mot-clé « comme Siri » (S42)

Détection de mot-clé vocal (**openWakeWord**, ONNX/CPU) en **flux WebSocket**.
Suite directe du POC S41 (`poc/`, décision **GO**) : ici on industrialise le moteur
prouvé en une vraie brique du registre.

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
docker compose up --build      # port 5800, image épinglée workplace/ecoute:0.1.0
# ou en local (Python 3.11 OBLIGATOIRE — pas de wheels onnxruntime en 3.14) :
python main.py
```

Le mot par défaut est le `hey_jarvis` pré-entraîné (l'assistant s'appelle « le Jarvis »).
Un modèle = un nom : le **palier payant S43** montera un modèle entraîné par marque via
la variable `WAKEWORD_MODELE` (même mécanique).

## Tests

```bash
# Hors ligne — détecteur en flux, sur les échantillons WAV du POC :
poc/.venv/bin/python -m pytest test_detecteur.py -v        # 10 verts

# LIVE — vrai service + vrai WebSocket (cf. journal S42) :
#   3 positifs « hey jarvis » → 1 réveil chacun ; 7 négatifs (parole FR,
#   « hey google » phonétiquement proche) → 0 réveil.
```

## Limite assumée (mesurée, cf. `poc/DECISION.md`)

Les modèles **pré-entraînés** sont calés sur les voix Piper et ne généralisent pas à
toute voix (`pos_alex` raté). Le produit doit **entraîner un modèle dédié par nom**
(job GPU = palier payant **S43**). Le `hey_jarvis` n'est qu'une preuve de moteur.
Le micro **navigateur** est structurellement conforme (getUserMedia → PCM 16k → trames),
prouvé ici sur fichiers à travers le vrai WebSocket.
