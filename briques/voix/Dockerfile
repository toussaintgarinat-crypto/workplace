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

COPY . .

# Pour le souverain Piper, monter un modèle de voix (.onnx + .onnx.json) et désigner son
# chemin via PIPER_VOICE (cf. docker-compose.yml). Sans modèle, la brique reste honnête :
# elle bascule sur un fournisseur hébergé configuré, ou rend un placeholder explicite.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5985"]
