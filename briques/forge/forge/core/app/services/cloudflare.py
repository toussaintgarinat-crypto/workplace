"""Cloudflare DNS — portage de ``forge/core/src/services/cloudflareService.ts`` (S132).

Crée un enregistrement A pour un déploiement client (mode domaine = cloudflare).
"""

from __future__ import annotations

import json
import os

import httpx


async def create_cloudflare_record(subdomain: str, ip: str) -> None:
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    zone_id = os.getenv("CLOUDFLARE_ZONE_ID")

    if not api_token or not zone_id:
        raise RuntimeError(
            "CLOUDFLARE_API_TOKEN et CLOUDFLARE_ZONE_ID doivent être configurés "
            "pour le mode Cloudflare auto."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={"type": "A", "name": subdomain, "content": ip, "ttl": 1, "proxied": False},
        )
    data = res.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare DNS error: {json.dumps(data.get('errors'))}")
