"""Client REST pour l'API PeerTube v1 — auth OAuth2 + cache de token."""
import httpx
import time
from typing import Optional


class PeerTubeClient:
    def __init__(self, url: str, user: str, password: str):
        self._url = url.rstrip("/")
        self._user = user
        self._password = password
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        async with httpx.AsyncClient() as c:
            oa = await c.get(f"{self._url}/api/v1/oauth-clients/local")
            oa.raise_for_status()
            oa_data = oa.json()
            resp = await c.post(f"{self._url}/api/v1/users/token", data={
                "client_id": oa_data["client_id"],
                "client_secret": oa_data["client_secret"],
                "grant_type": "password",
                "username": self._user,
                "password": self._password,
            })
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 86400)
        return self._token

    async def _headers(self) -> dict:
        return {"Authorization": f"Bearer {await self.token()}"}

    async def lister_videos(self, search: str = "", count: int = 20) -> list[dict]:
        params = {"count": count, "sort": "-publishedAt"}
        if search:
            params["search"] = search
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._url}/api/v1/videos",
                               params=params, headers=await self._headers())
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def info_video(self, uuid: str) -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.get(f"{self._url}/api/v1/videos/{uuid}",
                               headers=await self._headers())
            resp.raise_for_status()
            return resp.json()

    async def uploader_video(self, nom: str, description: str,
                              fichier_bytes: bytes, nom_fichier: str) -> dict:
        async with httpx.AsyncClient(timeout=300) as c:
            resp = await c.post(
                f"{self._url}/api/v1/videos/upload",
                headers=await self._headers(),
                data={"name": nom, "description": description, "channelId": 1},
                files={"videofile": (nom_fichier, fichier_bytes, "video/mp4")},
            )
            resp.raise_for_status()
            return resp.json()["video"]

    async def creer_live(self, nom: str, description: str = "") -> dict:
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{self._url}/api/v1/videos/live",
                headers=await self._headers(),
                json={"name": nom, "description": description,
                      "channelId": 1, "saveReplay": True},
            )
            resp.raise_for_status()
            uuid = resp.json()["video"]["uuid"]
            live_resp = await c.get(f"{self._url}/api/v1/videos/live/{uuid}",
                                    headers=await self._headers())
            live_resp.raise_for_status()
            live_info = live_resp.json()
            return {"uuid": uuid, "rtmpUrl": live_info["rtmpUrl"],
                    "streamKey": live_info["streamKey"]}
