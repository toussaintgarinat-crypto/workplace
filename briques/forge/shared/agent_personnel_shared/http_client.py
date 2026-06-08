"""S2SClient — wrapper httpx async avec retry + circuit breaker.

Pourquoi ce module ?
- Les appels inter-services (assistant → mempalace, assistant → forge, …)
  doivent dégrader gracieusement quand un backend tombe.
- httpx seul n'a ni retry ni circuit breaker → un service indispo
  saturait jusqu'ici les threads et provoquait des 500.
- Ce wrapper centralise : auth Bearer, retry exponentiel, ouverture
  du circuit après 5 échecs (réinitialisé après 30 s).

Garde-fous (cf. Sprint 99) :
- Streaming SSE NON supporté (long-lived, on ne peut pas retry/circuit).
  Les routes /chat/stream restent en `httpx.AsyncClient` direct.
- POST de création (`/drawers`, `/tasks`) sont retryés. Sur ces endpoints
  *non idempotents*, l'appelant doit accepter un éventuel doublon
  côté serveur (les services backend MemPalace/Forge dédupliquent par
  hash de contenu, ce qui rend l'opération de fait idempotente).
- Budget total max : 3 tentatives × wait_exponential (0.5 → 4 s) ≈ 12 s
  côté retry, + `timeout` httpx par tentative. Reste sous la barre
  des 30 s par défaut d'un proxy frontend.

Usage type :

```python
from agent_personnel_shared.http_client import S2SClient, S2SError

client = S2SClient(
    base_url="http://mempalace:8100",
    token=user_token,
    service_name="mempalace",
    timeout=5.0,
)
try:
    resp = await client.post("/v1/api/search", json={"query": q})
    data = resp.json()
except S2SError as exc:
    logger.warning("mempalace down: %s", exc)
    data = {"results": []}  # fallback gracieux
```
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

try:  # tenacity et circuitbreaker sont optionnels — fail loud à l'import seulement.
    from tenacity import (
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "tenacity manquant — ajoute `tenacity>=8` aux requirements du service hôte"
    ) from exc

try:
    import circuitbreaker
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "circuitbreaker manquant — ajoute `circuitbreaker>=2` aux requirements du service hôte"
    ) from exc


logger = logging.getLogger(__name__)


# Exception unifiée qu'on expose pour les fallbacks gracieux.
# - S2SCircuitOpenError : le circuit est ouvert (5 échecs récents)
# - S2SRequestError    : la requête a finalement échoué (timeout, 5xx, network)
S2SCircuitOpenError = circuitbreaker.CircuitBreakerError


class S2SRequestError(RuntimeError):
    """Erreur HTTP/réseau finale après épuisement des retries."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, original: Optional[BaseException] = None):
        super().__init__(message)
        self.status_code = status_code
        self.original = original


# Alias pratique : un fallback peut faire `except S2SError`.
S2SError = (S2SCircuitOpenError, S2SRequestError, httpx.HTTPError)


# ── Circuit breaker partagé par (service_name) ──────────────────────────────
#
# circuitbreaker.circuit() est un décorateur global : on ne peut pas paramétrer
# le nom dynamiquement par instance. On instancie donc un breaker par service
# au premier appel et on le cache.

_BREAKERS: dict[str, Any] = {}


def _is_breaker_failure(_exc_type: type, exc_value: BaseException) -> bool:
    """Prédicat de défaillance pour le circuit breaker.

    Compte comme échec (→ rapproche l'ouverture du circuit) :
    - les 5xx (le backend est en souffrance),
    - les timeouts et erreurs réseau.
    NE compte PAS un 4xx : c'est un bug de payload côté appelant, pas une
    panne du backend, donc il ne doit pas casser le circuit.
    """
    if isinstance(exc_value, httpx.HTTPStatusError):
        return exc_value.response.status_code >= 500
    return isinstance(exc_value, httpx.HTTPError)


def _get_breaker(service_name: str):
    """Retourne (et crée si besoin) le circuit breaker dédié à `service_name`."""
    bkr = _BREAKERS.get(service_name)
    if bkr is not None:
        return bkr
    bkr = circuitbreaker.CircuitBreaker(
        name=f"s2s:{service_name}",
        failure_threshold=5,
        recovery_timeout=30,
        expected_exception=_is_breaker_failure,
    )
    _BREAKERS[service_name] = bkr
    return bkr


class S2SClient:
    """Client httpx wrappé avec retry + circuit breaker pour appels inter-services.

    Paramètres :
        base_url     : URL racine du service cible (ex: http://mempalace:8100)
        token        : Bearer token optionnel (injecté dans Authorization)
        service_name : étiquette utilisée par le circuit breaker + logs
        timeout      : timeout httpx PAR TENTATIVE (3 tentatives max)
    """

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        service_name: str = "unknown",
        timeout: float = 5.0,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.service_name = service_name
        self.timeout = timeout
        self._breaker = _get_breaker(service_name)

    # ── Cœur : une seule méthode `_request` ───────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Effectue la requête avec retry exponentiel + circuit breaker."""

        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.base}{path}"

        # Tenacity gère les retries (timeouts + erreurs réseau uniquement —
        # on ne retry PAS sur les erreurs HTTP côté serveur : un 4xx est
        # un bug de payload, un 5xx est compté par le circuit breaker).
        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=0.5, max=4),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
            reraise=True,
        )
        async def _do_request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.request(method, url, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp

        # Circuit breaker : on l'invoque manuellement (le décorateur de
        # circuitbreaker ne joue pas bien avec les coroutines async).
        if self._breaker.opened:
            raise S2SCircuitOpenError(
                f"Circuit open for {self.service_name} (recovers in <{self._breaker._recovery_timeout}s)"
            )

        # Le circuit breaker s'utilise comme context manager : à la sortie il
        # consulte le prédicat `_is_breaker_failure` pour comptabiliser succès
        # ou échec (5xx/timeout/réseau = échec, 4xx = neutre). On évite ainsi
        # de toucher aux méthodes privées de la lib (API instable selon version).
        try:
            with self._breaker:
                response = await _do_request()
        except httpx.HTTPStatusError as exc:
            raise S2SRequestError(
                f"{self.service_name} {method} {path} → HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                original=exc,
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
            raise S2SRequestError(
                f"{self.service_name} {method} {path} → {type(exc).__name__}: {exc}",
                original=exc,
            ) from exc
        else:
            return response

    # ── Verbes HTTP ───────────────────────────────────────────────────────

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self._request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> httpx.Response:
        return await self._request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> httpx.Response:
        return await self._request("PUT", path, **kw)

    async def delete(self, path: str, **kw: Any) -> httpx.Response:
        return await self._request("DELETE", path, **kw)

    async def patch(self, path: str, **kw: Any) -> httpx.Response:
        return await self._request("PATCH", path, **kw)


__all__ = [
    "S2SClient",
    "S2SError",
    "S2SRequestError",
    "S2SCircuitOpenError",
]
