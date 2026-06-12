# S41 — POC openWakeWord : décision **GO** (avec garde-fous)

> 5ᵉ incrément du plan « Multilingue + voix wake word ».
> Question tranchée : **openWakeWord est-il viable pour une détection de mot-clé « comme Siri », y compris en français, sur notre infra ?**
> **Réponse : GO.** Le moteur tourne chez nous, distingue le mot-clé du bruit sans faux positif, et le chemin de données FR est ouvert. On peut bâtir la brique `ecoute` (S42).

Reproduction : voir `README.md` (un script de synthèse + un script de détection, ~2 min, hors ligne après le 1ᵉʳ téléchargement des modèles).

---

## Ce qui a été prouvé en vrai (2026-06-12)

### 1. Le moteur de détection tourne sur notre infra ✅
`openwakeword==0.6.0` + `onnxruntime==1.23.2` installés dans un venv **Python 3.11** (les wheels ML ne sont pas fiables en 3.14, voir garde-fou ci-dessous). Modèles ONNX pré-entraînés téléchargés (~1 Mo chacun), inférence **CPU**, pas de GPU requis à la détection. Le modèle pré-entraîné **`hey_jarvis`** est livré d'origine — heureux hasard, l'assistant s'appelle déjà « le Jarvis ».

### 2. Il sépare le mot-clé du reste, **sans faux positif** ✅
`detection.py` fait défiler `hey_jarvis` sur 11 clips synthétisés (TTS macOS `say`, ramenés en 16 kHz mono par `afconvert`), par fenêtres de 80 ms — exactement la boucle qu'exécutera la brique `ecoute`. Seuil 0.5.

| Clip | Attendu | Score max | Verdict |
|---|---|---|---|
| `pos_phrase` (« hey jarvis, what's the weather », Samantha) | POSITIF | **0.999** | 🔔 détecté |
| `pos_samantha` (« hey jarvis ») | POSITIF | **0.927** | 🔔 détecté |
| `pos_daniel` (« hey jarvis ») | POSITIF | **0.815** | 🔔 détecté |
| `pos_alex` (« hey jarvis », voix robotique, 0,60 s) | POSITIF | 0.005 | — raté (voir §4) |
| 7 négatifs (`what time is it`, `hello there`, `hey google…`, **`bonjour comment ça va`** FR, + 3 clips FR « Oria ») | négatif | **0.000–0.001** | — silence ✅ |

**Faux positifs : 0/7**, y compris sur de la parole **française** et sur « hey google » (phonétiquement proche). C'est le résultat qui compte pour un wake word : on préfère rater une fois que se déclencher tout seul.

### 3. Le chemin de données FR est ouvert ✅
Le risque n°1 du plan était « le français ». Les voix **françaises locales** (`say -v "Eddy (France)" / Flo / Thomas`) synthétisent proprement un nom inventé (« Oria ») — ce qui prouve que la **génération des exemples d'entraînement en français est faisable**. Le pipeline officiel openWakeWord utilise **Piper** (mêmes voix neuronales FR) pour produire des milliers de variantes ; on a démontré le principe localement sans dépendre de Piper pour ce POC.

### 4. Limite mesurée, honnête : le pré-entraîné n'est pas omni-voix
`pos_alex` (rendu robotique, 0,60 s) marque 0.005. En préfixant 0,5 s de silence (simule le flux continu qui amorce le buffer glissant), il remonte à **0.306** — mais reste sous 0.5. Lecture : **les modèles pré-entraînés sont calés sur les voix Piper et ne généralisent pas à n'importe quelle voix de synthèse `say`.** Ce n'est pas un défaut du moteur : c'est exactement pourquoi le produit **entraîne un modèle dédié par nom** sur ses propres données Piper (palier custom, S43). Le `hey_jarvis` pré-entraîné n'est ici qu'une **preuve de moteur empruntée**, pas le modèle final.

### 5. Arabe (point ouvert du plan) : risqué, confirmé
Une seule voix TTS arabe locale (`Majed`, `ar_001`) ; les voix Piper arabes sont rares et inégales. La génération de données AR de qualité reste le **maillon faible** → l'arabe reste justifié en incrément RTL dédié **S44**, avec la voix AR à re-valider à ce moment.

---

## Garde-fous pour l'industrialisation (S42/S43)

1. **Python 3.11 obligatoire pour la brique `ecoute`** : `onnxruntime`/`numpy` n'ont pas de wheels fiables en 3.14. À épingler dans le Dockerfile de la brique (image `python:3.11-slim`).
2. **Entraîner ses propres modèles** : ne pas se reposer sur les pré-entraînés au-delà du POC. Pipeline = Piper (voix FR/EN/ES) → openWakeWord training. L'entraînement réel d'un nom est le **job GPU** (Colab/serveur) du palier payant S43 ; il n'a **pas** été exécuté ici (ce POC ne prétend pas l'avoir fait).
3. **Seuil + double-confirmation** : 0.5 par défaut donne 0 faux positif sur ce jeu ; prévoir un réglage et éventuellement une 2ᵉ fenêtre de confirmation pour la robustesse en conditions réelles (bruit, micro lointain).
4. **Repli gardé en réserve** : **Picovoice Porcupine** si openWakeWord déçoit en conditions réelles ou si on veut du « nom libre instantané » navigateur (cf. plan).
5. **Preuve micro live non faite** : ce POC détecte sur **fichiers** synthétisés, pas sur un micro en direct. La capture micro temps-réel (WebSocket façon Unmute) est précisément le livrable **S42**.

---

## Verdict

**GO pour S42** (brique `ecoute` + fournisseur `creerWakeWord()` dans `core/main.py`).
Moteur validé sur notre infra, rejet du bruit excellent (FR inclus), chemin de données FR ouvert.
Réserves portées en clair : entraînement custom = job GPU (S43), micro live = S42, arabe = S44.
