"""Administration du Gateway (LiteLLM) — best-effort + verdict honnête.

Enregistre ou retire un modèle dans LiteLLM via son API admin (/model/new, /model/delete).
Jamais de levée d'exception réseau ou HTTP : on retourne toujours un dict {ok, erreur, …}.

Variables d'environnement attendues :
  LITELLM_URL        : URL de base du Gateway (ex. http://host.docker.internal:4000).
                       Si absente → {ok: False, erreur: "LITELLM_URL non configuré"}.
  LITELLM_MASTER_KEY : clé maître LiteLLM (header Authorization: Bearer <clé>).
                       Facultative (certains déploiements n'en ont pas).

Motif injectable : les fonctions acceptent un ``client`` httpx.AsyncClient en paramètre
pour rester 100 % testables hors-ligne (jamais d'appel réseau réel en test).
"""
import os
from typing import Optional

import httpx


def _gateway_url() -> str:
    """Renvoie l'URL du Gateway (sans slash final). Vide si LITELLM_URL non configuré."""
    return os.getenv("LITELLM_URL", "").rstrip("/")


def _headers_admin() -> dict:
    """Headers d'authentification pour l'API admin LiteLLM."""
    cle = os.getenv("LITELLM_MASTER_KEY", "")
    return {"Authorization": f"Bearer {cle}"} if cle else {}


async def enregistrer_modele(
    model_name: str,
    api_base: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Enregistre un modèle dans LiteLLM (POST /model/new). Best-effort.

    Retourne un dict :
      {ok: bool, erreur: str|None, model_id: str|None, model_name: str}

    Ne lève jamais sur erreur réseau ou HTTP.
    """
    url = _gateway_url()
    if not url:
        return {
            "ok": False,
            "erreur": "LITELLM_URL non configuré — enregistrement ignoré",
            "model_id": None,
            "model_name": model_name,
        }

    corps = {
        "model_name": model_name,
        "litellm_params": {
            "model": model_name,
            "api_base": api_base,
            "api_key": "none",
        },
    }

    propre = client is None
    client = client or httpx.AsyncClient(timeout=5.0)
    try:
        r = await client.post(
            f"{url}/model/new",
            json=corps,
            headers=_headers_admin(),
        )
        if r.status_code < 400:
            try:
                data = r.json()
            except Exception:
                data = {}
            # LiteLLM renvoie le model_id sous différentes clés selon la version.
            model_id = data.get("model_id") or data.get("id") or None
            return {
                "ok": True,
                "erreur": None,
                "model_id": model_id,
                "model_name": model_name,
            }
        else:
            return {
                "ok": False,
                "erreur": f"HTTP {r.status_code} : {r.text[:200]}",
                "model_id": None,
                "model_name": model_name,
            }
    except Exception as exc:  # noqa: BLE001 — on reste honnête
        return {
            "ok": False,
            "erreur": str(exc) or exc.__class__.__name__,
            "model_id": None,
            "model_name": model_name,
        }
    finally:
        if propre:
            await client.aclose()


async def retirer_modele(
    model_id: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Retire un modèle de LiteLLM (POST /model/delete). Best-effort.

    Retourne un dict : {ok: bool, erreur: str|None}.
    Ne lève jamais sur erreur réseau ou HTTP.
    """
    url = _gateway_url()
    if not url:
        return {"ok": False, "erreur": "LITELLM_URL non configuré — retrait ignoré"}

    propre = client is None
    client = client or httpx.AsyncClient(timeout=5.0)
    try:
        r = await client.post(
            f"{url}/model/delete",
            json={"id": model_id},
            headers=_headers_admin(),
        )
        if r.status_code < 400:
            return {"ok": True, "erreur": None}
        else:
            return {"ok": False, "erreur": f"HTTP {r.status_code} : {r.text[:200]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "erreur": str(exc) or exc.__class__.__name__}
    finally:
        if propre:
            await client.aclose()
