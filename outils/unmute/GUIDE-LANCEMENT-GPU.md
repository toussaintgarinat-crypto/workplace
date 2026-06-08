# Runbook — premier lancement réel d'Unmute (jour du GPU)

> But : passer de « préparé » à « ça parle pour de vrai », **étape par étape**, avec un
> protocole de **validation de l'audio** (la seule partie non testable sans GPU). Garde
> ce fichier ouvert le jour J. Tout est réversible (retour Navigateur en 1 clic).
>
> Rappel honnête : en mode Unmute, c'est Unmute qui mène la conversation via ton LLM
> (Gateway) — **sans** la boucle à outils de l'assistant. C'est le mode *brainstorming
> vocal*. Pour piloter l'usine à la voix avec confirmations, garde le mode **Navigateur**.

---

## 0. Pré-vol (5 min) — vérifier la machine GPU
Sur la machine Linux à GPU :
```bash
nvidia-smi                       # GPU vu ? VRAM ≥ 16 Go libres ?
docker info | grep -i runtime    # 'nvidia' présent (nvidia-container-toolkit installé)
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi   # GPU dans un conteneur
```
✅ Attendu : `nvidia-smi` liste le GPU **dans** le conteneur. Sinon → installer
`nvidia-container-toolkit` puis `sudo systemctl restart docker`.

Budget VRAM : STT ≈ 2,5 Go + TTS ≈ 5,3 Go (+ marge). Le **LLM ne tourne pas ici** (il est
sur la Gateway de Workplace) — c'est tout l'intérêt de l'override.

---

## 1. Rendre la Gateway de Workplace joignable depuis la machine GPU
Unmute (backend) doit atteindre la Gateway LiteLLM (port **4001**).

- **Même machine** que Workplace : `KYUTAI_LLM_URL=http://host.docker.internal:4001/v1`
  (l'override ajoute déjà `host.docker.internal:host-gateway` pour Linux).
- **GPU distant** : ouvre/forward le port 4001 de la machine Workplace.
  - rapide et sûr : tunnel SSH depuis la machine GPU
    ```bash
    ssh -N -L 4001:localhost:4001 user@machine-workplace
    # puis KYUTAI_LLM_URL=http://host.docker.internal:4001/v1
    ```
  - ou IP directe LAN : `KYUTAI_LLM_URL=http://<IP_WORKPLACE>:4001/v1`

Test depuis la machine GPU (doit répondre, clé = `LITELLM_MASTER_KEY`) :
```bash
curl -s http://localhost:4001/v1/models -H "Authorization: Bearer sk-master-change-this" | head -c 300
```
✅ Attendu : la liste JSON des modèles. ❌ 401 → mauvaise clé ; refus de connexion →
port non joignable (revoir tunnel/parefeu).

---

## 2. Choisir un bon modèle côté Gateway
Unmute enchaîne des complétions courtes en continu → privilégie un modèle **rapide**.
Dans `briques/gateway/litellm_config.yaml`, assure-toi qu'un modèle léger existe
(`openai/gpt-4o-mini` convient). Mets son nom dans `.env` → `KYUTAI_LLM_MODEL`.
> Si plus tard tu as un LLM local rapide (cf. `GUIDE-llama-cpp.md`), pointe-le ici pour
> du 100 % local (STT+TTS sur le GPU, LLM via Gateway→llama.cpp/Ollama).

---

## 3. Cloner, configurer, lancer Unmute
```bash
cd outils/unmute
git clone https://github.com/kyutai-labs/unmute .     # clone DANS ce dossier
cp .env.example .env                                  # puis édite .env (étapes 1–2)

# Lancer en pointant sur la Gateway (override Workplace par-dessus le compose officiel)
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
docker compose ps                                     # services up ?
```
Premier démarrage : téléchargement des poids STT/TTS Kyutai (HF token requis) → patiente.

### Vérifier chaque service
```bash
docker compose logs -f backend | grep -i -E "llm|ready|error"   # backend voit la Gateway ?
docker compose logs stt  | tail -20
docker compose logs tts  | tail -20
```
✅ Le backend doit logguer qu'il joint le LLM (pas de 401/timeout vers la Gateway).
❌ 401 → `KYUTAI_LLM_API_KEY` ; connection refused → réseau (étape 1) ; `extra_hosts`
manquant → l'override le pose, vérifie qu'il est bien chargé (`-f docker-compose.override.yml`).

### Valider le serveur AVANT notre front (test indépendant)
Le compose officiel sert **sa propre UI** (frontend, port 3000, via Traefik :80).
Ouvre-la dans un navigateur et parle : si Unmute répond là, **le serveur est bon** et tout
problème restant est côté intégration Workplace (étape 5). Ça isole le sujet proprement.

---

## 4. Trouver la bonne URL WebSocket
Notre client attaque `${url}` directement (sous-protocole `realtime`). Selon ton réseau :
- via Traefik/HTTPS : `wss://<domaine-ou-IP>/v1/realtime`
- backend exposé en clair : `ws://<IP_GPU>:8000/v1/realtime`
  (⚠ un dashboard servi en **https** ne peut pas ouvrir un **ws://** non sécurisé — sers
  alors le backend en `wss://` derrière Traefik, ou accède au dashboard en http.)

Test rapide de l'ouverture WS (depuis une machine cliente) :
```bash
# nécessite websocat ; sinon, fais-le dans la console du navigateur (étape 5)
websocat -v "ws://<IP_GPU>:8000/v1/realtime" --protocol realtime
```

---

## 5. Brancher dans Workplace + VALIDER l'audio (le cœur du sujet)
1. Dashboard → **Assistant → ⚙ Cerveau → Voix temps réel** → **Kyutai Unmute** + colle
   l'URL `…/v1/realtime` → **Enregistrer la voix**. (Persisté ; `VOIX` reconstruit à chaud.)
2. Clique **🎤** et parle.

### Méthode de validation (ouvre les DevTools → onglet *Network* → filtre *WS*)
Clique sur la connexion `/v1/realtime` → onglet **Messages** : tu vois les trames émises/reçues.
Vérifie, dans l'ordre, ces 4 points — et ajuste `creerUnmute()` dans `core/main.py` si besoin :

| # | À vérifier | Où regarder | Si ça diffère → ajuster |
|---|---|---|---|
| 1 | **Le handshake passe** (WS `open`, pas de close immédiat) | Network/WS status | URL/sous-protocole (étape 4) ; CORS/Traefik |
| 2 | **`session.update` accepté** (le serveur commence à répondre après) | 1ʳᵉ trame émise + réaction serveur | champs de `session` : compare à `unmute/openai_realtime_api_events.py` (modèle `SessionConfig`) et `voices.yaml` (nom de voix valide). Adapter l'objet envoyé dans `creerUnmute` (`{type:'session.update', session:{…}}`). |
| 3 | **Ta voix est transcrite** (events `…input_audio_transcription.delta`) | trames reçues | si vide : format **micro**. Vérifie `input_audio_buffer.append` : encodage **Opus 24 kHz mono base64**. Notre client encode via **WebCodecs** (`AudioEncoder` opus, 24 kHz). Si le serveur attend des frames de taille fixe (ex. 20 ms), règle la taille de bloc du `ScriptProcessor`/worklet. |
| 4 | **Tu entends la réponse** (events `response.audio.delta`) | trames reçues + son | si muet : décodage **sortie**. On décode via `AudioDecoder` opus → lecture WebAudio. Si rien : vérifie que `m.delta` est bien du base64 d'**un paquet Opus** ; certains serveurs encapsulent (en-tête/longueur) → retire l'enveloppe avant `decode`. Le texte (`response.text.delta`) doit s'afficher même si l'audio cale → bon repère pour isoler « LLM OK, audio à régler ». |

> Référence amont à garder sous la main pour les noms exacts :
> `unmute/openai_realtime_api_events.py` (tous les events + champs), `voices.yaml` (voix),
> `docs/browser_backend_communication.md` (séquence + audio).

### Symptômes fréquents → cause probable
- **Texte OK, pas de son** : décodage Opus de sortie (point 4) — enveloppe/format.
- **Aucune transcription** : encodage micro (point 3) — taille de bloc / Opus.
- **WS se ferme tout de suite** : `session.update` invalide (point 2) ou voix inexistante.
- **`response` jamais émis** : le backend ne joint pas le LLM → revoir étapes 1–2 (Gateway).
- **WebCodecs indisponible** : navigateur trop ancien → Chrome/Edge récents.

---

## 6. Retour arrière (toujours possible)
⚙ Cerveau → Voix → **Navigateur** → Enregistrer. Workplace repasse en Web Speech (local,
avec outils). Côté GPU : `docker compose down` dans `outils/unmute/`.

---

## 7. Quand l'audio est validé
- Note dans `WORKPLACE.md` (journal) la **forme exacte** du `session.update` et le format
  audio qui ont marché → ça fige le contrat pour la prochaine fois.
- Si tu veux la voix au démarrage : on pourra ajouter le lancement d'Unmute (machine GPU)
  au `Lancer Workplace.command` — à faire seulement si le serveur est sur la même machine.

## Aide-mémoire des fichiers
- `docker-compose.override.yml` — pointe le backend sur la Gateway, coupe le vLLM embarqué.
- `.env.example` → `.env` — `KYUTAI_LLM_URL` / `KYUTAI_LLM_API_KEY` / `KYUTAI_LLM_MODEL` / HF token.
- `LISEZMOI.md` — vue d'ensemble + nuance « brainstorming vs outils ».
- Client front : `creerUnmute(url)` dans `core/main.py` (c'est CE code qu'on ajuste au point 5).
