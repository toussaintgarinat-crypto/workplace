import json
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

import httpx

CONFIG_DIR = Path.home() / ".memory"
CONFIG_FILE = CONFIG_DIR / "config.json"
API_BASE = "http://localhost:8000/api/v1"


class MemoryClient:
    def __init__(self):
        self.config = self._load_config()
        self._client = httpx.Client(base_url=API_BASE, headers=self._headers())
        self._space_id: Optional[str] = None

    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
        return {}

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2))

    def _headers(self) -> dict:
        token = self.config.get("token")
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    @property
    def space_id(self) -> str:
        if self._space_id:
            return self._space_id
        sid = self.config.get("space_id")
        if not sid:
            print("No space selected. Run 'memory init' or 'memory config set-space <uuid>'.")
            raise SystemExit(1)
        return sid

    @space_id.setter
    def space_id(self, value: str):
        self._space_id = value

    def register(self, email: str, password: str, display_name: str = "") -> dict:
        resp = self._client.post("/auth/register", json={
            "email": email, "password": password, "display_name": display_name,
        })
        self._handle_error(resp)
        return resp.json()

    def login(self, email: str, password: str) -> dict:
        resp = self._client.post("/auth/login", json={"email": email, "password": password})
        self._handle_error(resp)
        data = resp.json()
        self.config["token"] = data["access_token"]
        self._save_config()
        self._client.headers.update(self._headers())
        return data

    def logout(self):
        self.config.pop("token", None)
        self._save_config()
        self._client.headers.pop("Authorization", None)
        print("Logged out.")

    def init_space(self, name: str = "My Memory", description: str = "") -> dict:
        resp = self._client.post("/spaces", json={"name": name, "description": description})
        self._handle_error(resp)
        data = resp.json()
        self.config["space_id"] = str(data["id"])
        self._save_config()
        return data

    def list_spaces(self) -> list[dict]:
        resp = self._client.get("/spaces")
        self._handle_error(resp)
        return resp.json()

    def set_space(self, space_id: str):
        self.config["space_id"] = space_id
        self._save_config()

    def create_node(self, type: str, title: str, content_md: str = "",
                    frontmatter: dict = None, location: dict = None,
                    source_url: str = None, captured_from: str = None) -> dict:
        payload = {
            "type": type,
            "title": title,
            "content_md": content_md,
            "frontmatter": frontmatter or {},
        }
        if location:
            payload["location"] = location
        if source_url:
            payload["source_url"] = source_url
        if captured_from:
            payload["captured_from"] = captured_from
        resp = self._client.post(f"/spaces/{self.space_id}/nodes", json=payload)
        self._handle_error(resp)
        return resp.json()

    def get_node(self, node_id: str) -> dict:
        resp = self._client.get(f"/spaces/{self.space_id}/nodes/{node_id}")
        self._handle_error(resp)
        return resp.json()

    def update_node(self, node_id: str, **kwargs) -> dict:
        resp = self._client.put(f"/spaces/{self.space_id}/nodes/{node_id}", json=kwargs)
        self._handle_error(resp)
        return resp.json()

    def delete_node(self, node_id: str) -> dict:
        resp = self._client.delete(f"/spaces/{self.space_id}/nodes/{node_id}")
        self._handle_error(resp)
        return resp.json()

    def update_stage(self, node_id: str, stage: str, reason: str = None) -> dict:
        payload = {"stage": stage}
        if reason:
            payload["reason"] = reason
        resp = self._client.patch(f"/spaces/{self.space_id}/nodes/{node_id}/stage", json=payload)
        self._handle_error(resp)
        return resp.json()

    def update_location(self, node_id: str, wing: str, room: str, drawer: str = None) -> dict:
        payload = {"wing": wing, "room": room}
        if drawer:
            payload["drawer"] = drawer
        resp = self._client.put(f"/spaces/{self.space_id}/nodes/{node_id}/location", json=payload)
        self._handle_error(resp)
        return resp.json()

    def touch_node(self, node_id: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/nodes/{node_id}/touch")
        self._handle_error(resp)
        return resp.json()

    def list_nodes(self, type: str = None, stage: str = None, status: str = "active",
                   wing: str = None, room: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
        params = {"limit": limit, "offset": offset, "status": status}
        if type:
            params["type"] = type
        if stage:
            params["stage"] = stage
        if wing:
            params["wing"] = wing
        if room:
            params["room"] = room
        resp = self._client.get(f"/spaces/{self.space_id}/nodes", params=params)
        self._handle_error(resp)
        return resp.json()

    def search(self, q: str, type: str = None, stage: str = None, limit: int = 20) -> list[dict]:
        params = {"q": q, "limit": limit}
        if type:
            params["type"] = type
        if stage:
            params["stage"] = stage
        resp = self._client.get(f"/spaces/{self.space_id}/search", params=params)
        self._handle_error(resp)
        return resp.json()

    def semantic_search(self, query: str, limit: int = 10, stage_filter: str = None,
                        type_filter: str = None) -> list[dict]:
        payload = {"query": query, "limit": limit}
        if stage_filter:
            payload["stage_filter"] = stage_filter
        if type_filter:
            payload["type_filter"] = type_filter
        resp = self._client.post(f"/spaces/{self.space_id}/search/semantic", json=payload)
        self._handle_error(resp)
        return resp.json()

    def get_palace(self) -> dict:
        resp = self._client.get(f"/spaces/{self.space_id}/palace")
        self._handle_error(resp)
        return resp.json()

    def create_wing(self, name: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/palace/wing", json={"name": name})
        self._handle_error(resp)
        return resp.json()

    def create_room(self, wing: str, name: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/palace/room", json={"wing": wing, "name": name})
        self._handle_error(resp)
        return resp.json()

    def create_drawer(self, wing: str, room: str, name: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/palace/drawer", json={"wing": wing, "room": room, "name": name})
        self._handle_error(resp)
        return resp.json()

    def get_graph(self, depth: int = 2, root: str = None) -> dict:
        params = {"depth": depth}
        if root:
            params["root"] = root
        resp = self._client.get(f"/spaces/{self.space_id}/graph", params=params)
        self._handle_error(resp)
        return resp.json()

    def create_edge(self, source_id: str, target_id: str, type: str = "related", weight: float = 1.0) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/graph/edges", json={
            "source_id": source_id, "target_id": target_id, "type": type, "weight": weight,
        })
        self._handle_error(resp)
        return resp.json()

    def delete_edge(self, edge_id: str) -> dict:
        resp = self._client.delete(f"/spaces/{self.space_id}/graph/edges/{edge_id}")
        self._handle_error(resp)
        return resp.json()

    def find_path(self, source: str, target: str) -> list[dict]:
        resp = self._client.get(f"/spaces/{self.space_id}/graph/path", params={"source": source, "target": target})
        self._handle_error(resp)
        return resp.json()

    def get_aging_nodes(self) -> list[dict]:
        resp = self._client.get(f"/spaces/{self.space_id}/nodes/aging")
        self._handle_error(resp)
        return resp.json()

    def run_tiers(self) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/maintenance/tiers")
        self._handle_error(resp)
        return resp.json()

    def gardien_config(self) -> dict:
        resp = self._client.get(f"/spaces/{self.space_id}/gardien/config")
        self._handle_error(resp)
        return resp.json()

    def gardien_set_config(self, config: dict) -> dict:
        resp = self._client.put(f"/spaces/{self.space_id}/gardien/config", json=config)
        self._handle_error(resp)
        return resp.json()

    def gardien_run(self) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/gardien/run")
        self._handle_error(resp)
        return resp.json()

    def gardien_suggestions(self) -> list[dict]:
        resp = self._client.get(f"/spaces/{self.space_id}/gardien/suggestions")
        self._handle_error(resp)
        return resp.json()

    def gardien_accept(self, suggestion_id: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/gardien/suggestions/{suggestion_id}/accept")
        self._handle_error(resp)
        return resp.json()

    def gardien_reject(self, suggestion_id: str) -> dict:
        resp = self._client.post(f"/spaces/{self.space_id}/gardien/suggestions/{suggestion_id}/reject")
        self._handle_error(resp)
        return resp.json()

    def gardien_log(self) -> list[dict]:
        resp = self._client.get(f"/spaces/{self.space_id}/gardien/log")
        self._handle_error(resp)
        return resp.json()

    def export(self, format: str = "json") -> dict | str:
        resp = self._client.get(f"/spaces/{self.space_id}/export", params={"format": format})
        self._handle_error(resp)
        if format == "markdown":
            return resp.text
        return resp.json()

    def stats(self) -> dict:
        resp = self._client.get(f"/spaces/{self.space_id}/stats")
        if resp.status_code >= 400:
            return {"total": 0, "types": {}, "stages": {}, "tiers": {}}
        data = resp.json()
        return {
            "total": data.get("total_nodes", 0),
            "types": data.get("by_type", {}),
            "stages": data.get("by_stage", {}),
            "tiers": data.get("by_tier", {}),
        }

    def _handle_error(self, resp: httpx.Response):
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            print(f"Error [{resp.status_code}]: {detail}")
            raise SystemExit(1)
