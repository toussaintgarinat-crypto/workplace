FROM python:3.12-slim

WORKDIR /app

# Le moteur SOUVERAIN = le binaire Piper PRÉCOMPILÉ (auto-contenu : espeak-ng-data + libs
# incluses). Plus fiable que le pip `piper-tts` (dont la dépendance piper-phonemize n'a pas
# de wheel hors x86). Téléchargé selon l'architecture de la cible (TARGETARCH).
ARG TARGETARCH
# ffmpeg : conversion WAV (sortie Piper) → Ogg/Opus pour la bulle vocale Telegram (sendVoice).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && case "${TARGETARCH:-amd64}" in \
         amd64) PARCH=x86_64 ;; \
         arm64) PARCH=aarch64 ;; \
         *)     PARCH=x86_64 ;; \
       esac \
    && curl -sSL -o /tmp/piper.tgz \
       "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_${PARCH}.tar.gz" \
    && tar -xzf /tmp/piper.tgz -C /opt \
    && rm /tmp/piper.tgz

# Le binaire et ses bibliothèques (libpiper_phonemize…) vivent dans /opt/piper.
ENV PIPER_BIN=/opt/piper/piper
ENV LD_LIBRARY_PATH=/opt/piper

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Voix NATURELLE locale (Kokoro) — OPT-IN au BUILD (INSTALL_KOKORO=1) ──────────
# Lourd (PyTorch) : installé seulement si demandé (cf. docker-compose.yml build.args).
# espeak-ng = phonémisation FR pour Kokoro. Au runtime, activer avec VOIX_KOKORO=1.
ARG INSTALL_KOKORO=0
RUN if [ "$INSTALL_KOKORO" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends espeak-ng \
      && rm -rf /var/lib/apt/lists/* \
      && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
      && pip install --no-cache-dir kokoro soundfile "misaki[fr]"; \
    fi

# ── Voix de LECTURE haut de gamme : Coqui XTTS-v2 — OPT-IN au BUILD (INSTALL_COQUI=1) ──
# Multilingue + CLONAGE de voix (point d'entrée du sprint S107). PLUS LOURD que Kokoro
# (torch + coqui-tts ; le modèle XTTS ~1,8 Go est téléchargé au 1er appel, pas au build).
# CPU lent mais ACCEPTABLE pour la lecture (résumés, longs textes — la latence n'y gêne pas).
# espeak-ng = phonémisation ; torch CPU-only (no-op si déjà posé par le bloc Kokoro).
# ⚠ Licence du modèle XTTS-v2 = CPML (non commerciale) : perso OK, commercial à vérifier.
# Au runtime, activer avec VOIX_COQUI=1 (cf. docker-compose.yml).
# ⚠ Pièges d'install (torch ≥2.9) : (1) torchaudio requis par XTTS ; (2) extra [codec] =
# torchcodec, requis depuis torch 2.9 pour l'IO audio (s'appuie sur les libs ffmpeg, déjà là) ;
# (3) transformers ÉPINGLÉ <5 : la 5.x a retiré `isin_mps_friendly` → coqui-tts 0.27 ne
# s'importe plus sinon ; (4) data espeak-ng symlinkée ci-dessous (binaire la cherche ailleurs).
ARG INSTALL_COQUI=0
RUN if [ "$INSTALL_COQUI" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends espeak-ng \
      && rm -rf /var/lib/apt/lists/* \
      # Debian range la data espeak-ng sous /usr/lib/<arch>/espeak-ng-data, mais le binaire la
      # cherche par défaut dans /usr/share/espeak-ng-data (absent) → erreur « phontab introuvable ».
      # Symlink robuste (toutes archis) vers le dossier réel repéré via dpkg.
      && D="$(dirname "$(dpkg -L espeak-ng-data | grep -m1 'espeak-ng-data/phontab$')")" \
      && ln -sfn "$D" /usr/share/espeak-ng-data \
      && pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
      && pip install --no-cache-dir "coqui-tts[codec]" "transformers>=4.57,<5"; \
    fi

COPY . .

# Pour le souverain Piper, monter un modèle de voix (.onnx + .onnx.json) et désigner son
# chemin via PIPER_VOICE (cf. docker-compose.yml). Sans modèle, la brique reste honnête :
# elle bascule sur un fournisseur hébergé configuré, ou rend un placeholder explicite.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5985"]
