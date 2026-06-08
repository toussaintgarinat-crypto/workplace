"""Harnais de tests de parité Python vs Bun.

Pierre angulaire de la stratégie strangler (cf. roadmap S126-S137) : AVANT de
débrancher une route Bun au profit de son portage Python, on prouve que les deux
implémentations renvoient des réponses équivalentes sur les mêmes entrées.

Utilisation type (sprints S127+) :

    from tests.parity.harness import assert_parity

    @pytest.mark.parity
    async def test_ventures_list_parity(py_client, bun_url, auth_headers):
        await assert_parity(
            py_client, bun_url,
            method="GET", path="/api/ventures",
            headers=auth_headers,
            ignore_keys={"created_at", "updated_at"},   # champs volatils
        )

En S126 (socle), aucune route n'est portée : ``assert_parity`` n'est pas encore
appelé sur du métier, mais sa logique de normalisation/diff est testée
unitairement (``test_parity_harness.py``) pour garantir le filet de sécurité.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

# Clés volatiles ignorées par défaut lors de la comparaison de bodies JSON.
DEFAULT_IGNORE_KEYS = {"created_at", "updated_at", "timestamp", "id", "trace_id"}


def normalize_json(value: Any, ignore_keys: Iterable[str] = ()) -> Any:
    """Normalise récursivement une valeur JSON pour comparaison stable.

    - retire les clés volatiles (`ignore_keys`) de chaque dict ;
    - trie les listes de scalaires (ordre non garanti entre implémentations) ;
    - laisse les listes d'objets dans l'ordre (l'ordre y est souvent significatif).
    """
    ignore = set(ignore_keys)
    if isinstance(value, dict):
        return {k: normalize_json(v, ignore) for k, v in sorted(value.items()) if k not in ignore}
    if isinstance(value, list):
        norm = [normalize_json(v, ignore) for v in value]
        if all(not isinstance(v, (dict, list)) for v in norm):
            return sorted(norm, key=repr)
        return norm
    return value


@dataclass
class ParityResult:
    method: str
    path: str
    status_py: int
    status_bun: int
    body_py: Any = None
    body_bun: Any = None
    diffs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.diffs

    def __str__(self) -> str:
        head = f"{self.method} {self.path} — py={self.status_py} bun={self.status_bun}"
        if self.ok:
            return f"PARITY OK · {head}"
        return f"PARITY FAIL · {head}\n  - " + "\n  - ".join(self.diffs)


async def compare(
    py_client: httpx.AsyncClient,
    bun_url: str,
    *,
    method: str,
    path: str,
    headers: dict | None = None,
    json: Any = None,
    params: dict | None = None,
    ignore_keys: Iterable[str] = DEFAULT_IGNORE_KEYS,
    compare_body: bool = True,
    timeout: float = 30.0,
) -> ParityResult:
    """Exécute la même requête côté Python et côté Bun, renvoie un ParityResult."""
    py_resp = await py_client.request(method, path, headers=headers, json=json, params=params)
    async with httpx.AsyncClient(base_url=bun_url, timeout=timeout) as bun_client:
        bun_resp = await bun_client.request(method, path, headers=headers, json=json, params=params)

    result = ParityResult(
        method=method,
        path=path,
        status_py=py_resp.status_code,
        status_bun=bun_resp.status_code,
    )

    if py_resp.status_code != bun_resp.status_code:
        result.diffs.append(f"status: py={py_resp.status_code} ≠ bun={bun_resp.status_code}")

    if compare_body:
        try:
            result.body_py = normalize_json(py_resp.json(), ignore_keys)
            result.body_bun = normalize_json(bun_resp.json(), ignore_keys)
            if result.body_py != result.body_bun:
                result.diffs.append("body JSON normalisé diffère")
        except ValueError:
            # corps non-JSON → compare brut
            if py_resp.content != bun_resp.content:
                result.diffs.append("body brut diffère")

    return result


async def assert_parity(py_client: httpx.AsyncClient, bun_url: str, **kwargs) -> ParityResult:
    """Variante assertive : lève AssertionError si la parité n'est pas atteinte."""
    result = await compare(py_client, bun_url, **kwargs)
    assert result.ok, str(result)
    return result


def bun_url_or_skip() -> str | None:
    """Renvoie PARITY_BUN_URL ou None (le test appelant doit alors être skip)."""
    return os.environ.get("PARITY_BUN_URL") or None
