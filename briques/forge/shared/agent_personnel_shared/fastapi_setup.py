"""Helpers FastAPI partagés : CORS depuis CSV, logging (texte ou JSON)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Iterable, Optional


def parse_origins(origins_str: str, default: Optional[Iterable[str]] = None) -> list[str]:
    """Parse une variable d'env CORS_ORIGINS au format CSV.

    `default` est utilisé si la chaîne est vide. None de chaque côté ⇒ liste vide.
    Les virgules en queue / espaces autour sont ignorés.
    """
    raw = (origins_str or "").strip()
    if not raw and default is not None:
        return [o for o in default if o]
    return [o.strip() for o in raw.split(",") if o.strip()]


def setup_cors(app, origins_str: str, *, default: Optional[Iterable[str]] = None,
               allow_credentials: bool = True) -> list[str]:
    """Configure le middleware CORS depuis une CSV. Renvoie la liste effective.

    Lance un warning si `*` est utilisé (incompatible avec allow_credentials=True
    selon la spec CORS ; le navigateur refusera).
    """
    from fastapi.middleware.cors import CORSMiddleware  # lazy import
    origins = parse_origins(origins_str, default=default)
    logger = logging.getLogger(__name__)
    if "*" in origins and allow_credentials:
        logger.warning(
            "CORS_ORIGINS contient '*' avec allow_credentials=True — "
            "le navigateur refusera les requêtes. Définis une liste explicite."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return origins


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure le root logger.

    fmt ∈ {"text", "json"}. En JSON, un format compatible Loki/Promtail est produit.
    Idempotent : on remplace les handlers existants.
    """
    lvl = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(lvl)
    # On remplace tous les handlers pour garantir l'idempotence (uvicorn en ajoute déjà).
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    if fmt.lower() == "json":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
    root.addHandler(handler)
