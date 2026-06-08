#!/usr/bin/env python3
"""Seed the database with demo data."""
import asyncio
import httpx
import json

API_BASE = "http://localhost:8000/api/v1"


async def main():
    async with httpx.AsyncClient(base_url=API_BASE) as client:
        resp = await client.post("/spaces", json={"name": "Demo Space", "description": "Données de démonstration"})
        space = resp.json()
        space_id = space["id"]
        print(f"Space created: {space_id}")

        seeds = [
            {"type": "input", "title": "Article sur les transformers", "content_md": "## Notes\nLes transformers ont révolutionné le NLP...", "frontmatter": {"priority": "medium", "captured_from": "web", "tags": ["ml", "transformers"]}},
            {"type": "projet", "title": "Site personnel v3", "content_md": "## Objectif\nRefaire mon site avec Astro.", "frontmatter": {"status": "active", "priority": "high", "next_actions": ["Choisir un thème", "Configurer le blog"], "tags": ["web", "astro"]}},
            {"type": "ressource", "title": "FastAPI Best Practices", "content_md": "## Patterns\nUtiliser des dépendances, des schémas Pydantic...", "frontmatter": {"resource_type": "article", "tags": ["python", "fastapi"]}},
            {"type": "casquette", "title": "Tech Lead", "content_md": "## Responsabilités\n- Review de code\n- Architecture technique", "frontmatter": {"role_name": "Tech Lead", "responsabilites": ["Review", "Mentoring"], "domaines": ["Python", "Architecture"]}},
        ]

        for s in seeds:
            resp = await client.post(f"/spaces/{space_id}/nodes", json=s)
            if resp.status_code == 201:
                node = resp.json()
                print(f"  Created: [{node['type']}] {node['title']}")
            else:
                print(f"  Error: {resp.text}")

        print(f"\nSeed complete! {len(seeds)} nodes created.")


if __name__ == "__main__":
    asyncio.run(main())
