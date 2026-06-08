"""HealthBuilder — schéma JSON commun pour les endpoints `/health` des services.

Format de sortie (top-level) :

```json
{
  "status": "ok" | "degraded" | "down",
  "service": "assistant",
  "version": "2.0.0",
  "uptime_seconds": 12345,
  "dependencies": [
    {"name": "postgres", "status": "ok"},
    {"name": "redis",    "status": "ok"},
    {"name": "mempalace","status": "degraded", "detail": "timeout"}
  ],
  "degraded": false,
  "metadata": {"auth_enabled": true, "readonly": false}
}
```

Usage :

```python
from agent_personnel_shared.health import HealthBuilder

builder = HealthBuilder("assistant", version="2.0.0", metadata={"auth_enabled": True})
await builder.check_redis(client)
await builder.check_dep_http("mempalace", "http://mempalace:8100/health")
return builder.build()
```

Conçu pour rester sans dépendance dure : `httpx` n'est importé que si on utilise
`check_dep_http`, et l'appelant peut toujours utiliser `add_dependency()` à la main.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# Démarrage du process — figé une seule fois (importable depuis n'importe quel service).
_PROCESS_START_TS = time.time()


# Statuts canoniques (string literal — pas d'enum pour rester JSON-serialisable trivialement).
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_DOWN = "down"


def _dep(name: str, status: str, detail: Optional[str] = None) -> dict:
    """Représentation interne d'une dépendance."""
    out: dict = {"name": name, "status": status}
    if detail:
        out["detail"] = detail
    return out


class HealthBuilder:
    """Construit un payload `/health` unifié pour un service.

    Le statut global est dérivé automatiquement :
    - une dépendance `down` → service `down`
    - une dépendance `degraded` (ou flag `degraded=True`) → service `degraded`
    - sinon → service `ok`
    """

    def __init__(
        self,
        service: str,
        *,
        version: str = "0.0.0",
        metadata: Optional[dict] = None,
        degraded: bool = False,
    ) -> None:
        self.service = service
        self.version = version
        self.metadata: dict = dict(metadata or {})
        self._dependencies: list[dict] = []
        self._degraded_flag = bool(degraded)

    # ── Construction manuelle ────────────────────────────────────────

    def add_dependency(self, name: str, status: str, detail: Optional[str] = None) -> "HealthBuilder":
        self._dependencies.append(_dep(name, status, detail))
        return self

    def set_degraded(self, value: bool = True) -> "HealthBuilder":
        self._degraded_flag = bool(value)
        return self

    def update_metadata(self, **kwargs: Any) -> "HealthBuilder":
        self.metadata.update(kwargs)
        return self

    # ── Checks utilitaires (best-effort, jamais lève) ────────────────

    async def check_redis(self, client: Any, name: str = "redis") -> "HealthBuilder":
        """Ping un client Redis async. None ou absence → status `down`."""
        if client is None:
            self.add_dependency(name, STATUS_DOWN, "unavailable")
            return self
        try:
            await client.ping()
            self.add_dependency(name, STATUS_OK)
        except Exception as exc:
            self.add_dependency(name, STATUS_DOWN, str(exc)[:120])
        return self

    async def check_pg(self, engine_or_db: Any, name: str = "postgres") -> "HealthBuilder":
        """Exécute un `SELECT 1` sur un engine SQLAlchemy ou un objet `databases.Database`."""
        if engine_or_db is None:
            self.add_dependency(name, STATUS_DOWN, "unavailable")
            return self
        try:
            # 1) databases.Database (assistant/mempalace)
            if hasattr(engine_or_db, "fetch_one") and callable(engine_or_db.fetch_one):
                await engine_or_db.fetch_one("SELECT 1")
                self.add_dependency(name, STATUS_OK)
                return self
            # 2) async sqlalchemy engine
            if hasattr(engine_or_db, "connect"):
                from sqlalchemy import text  # type: ignore

                async with engine_or_db.connect() as conn:  # type: ignore[attr-defined]
                    await conn.execute(text("SELECT 1"))
                self.add_dependency(name, STATUS_OK)
                return self
            self.add_dependency(name, STATUS_DEGRADED, "unknown engine type")
        except Exception as exc:
            self.add_dependency(name, STATUS_DOWN, str(exc)[:120])
        return self

    async def check_dep_http(
        self,
        name: str,
        url: str,
        *,
        timeout: float = 3.0,
        expected_status: Iterable[int] = (200, 204),
    ) -> "HealthBuilder":
        """GET HTTP best-effort vers un autre service (typiquement son `/health`)."""
        try:
            import httpx  # type: ignore
        except ImportError:
            self.add_dependency(name, STATUS_DEGRADED, "httpx missing")
            return self
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
            if resp.status_code in expected_status:
                self.add_dependency(name, STATUS_OK)
            else:
                self.add_dependency(name, STATUS_DEGRADED, f"HTTP {resp.status_code}")
        except Exception as exc:
            self.add_dependency(name, STATUS_DOWN, str(exc)[:120])
        return self

    # ── Build final ──────────────────────────────────────────────────

    def _compute_status(self) -> str:
        if any(d["status"] == STATUS_DOWN for d in self._dependencies):
            return STATUS_DOWN
        if self._degraded_flag or any(d["status"] == STATUS_DEGRADED for d in self._dependencies):
            return STATUS_DEGRADED
        return STATUS_OK

    def build(self) -> dict:
        status = self._compute_status()
        return {
            "status": status,
            "service": self.service,
            "version": self.version,
            "uptime_seconds": int(time.time() - _PROCESS_START_TS),
            "dependencies": list(self._dependencies),
            "degraded": status != STATUS_OK,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "HealthBuilder",
    "STATUS_OK",
    "STATUS_DEGRADED",
    "STATUS_DOWN",
]
