# Brique connecteurs (S214) — deux environnements Python dans une seule image.
#
# python:3.11 et PAS 3.12, à dessein : `airbyte` exige <3.13, mais surtout plusieurs
# connecteurs publiés sur PyPI exigent <3.12 (`airbyte-source-stripe`,
# `airbyte-source-declarative-manifest` au 2026-07-28). Une image 3.12 fermerait la porte
# à ces connecteurs-là sans le dire. Le filet `scripts/tests_briques.sh` lit ce `FROM` et
# teste donc la brique sous 3.11 — rien à déclarer ailleurs.
FROM python:3.11-slim

# Télémétrie PyAirbyte : ACTIVE par défaut (elle l'annonce au premier import). Coupée ici
# ET dans le compose — une brique de Workplace ne rend pas compte de son usage à un tiers.
ENV DO_NOT_TRACK=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── venv 1/2 : PyAirbyte, isolé ──────────────────────────────────────────────
# Isolé parce qu'il est INCO-INSTALLABLE avec la pile du parc (cf. requirements.txt).
# `python -m venv` SANS --system-site-packages : la cloison doit être étanche, sinon la
# brique importerait le pydantic de PyAirbyte et l'API tomberait au démarrage.
# C'est la couche la plus lourde (~700 Mo) et la plus stable : elle vient AVANT le code,
# pour qu'une modif de la brique ne la réinstalle pas.
RUN python -m venv /opt/pyairbyte \
 && /opt/pyairbyte/bin/pip install --no-cache-dir 'airbyte==0.53.2'

# ── venv 2/2 : l'API, sous les contraintes du parc ───────────────────────────
COPY briques/connecteurs/requirements.txt .
COPY constraints-workplace.txt /constraints-workplace.txt
RUN pip install --no-cache-dir -r requirements.txt -c /constraints-workplace.txt

COPY briques/connecteurs/ /app/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6200"]
