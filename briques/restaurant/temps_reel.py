"""Diffusion temps réel (WebSocket) de la brique « restaurant ».

Push live de deux flux, cloisonnés par restaurant :
  • canal CUISINE  « cuisine:{restaurant_id} » → nouvelles commandes, changements de statut ;
  • canal TABLE    « table:{table_id} »        → état d'addition (qui a payé, reste à payer).

Gestionnaire minimal en mémoire (un seul process) : un dict canal → set de WebSockets.
Si on passe multi-process plus tard, brancher un bus (Redis pub/sub) derrière la même
interface `diffuser(canal, message)`. L'isolation tient déjà au niveau du NOM de canal :
on ne s'abonne qu'à son restaurant / sa table (le code de table fait capability)."""
from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket


class Diffuseur:
    def __init__(self) -> None:
        self._abonnes: dict[str, set[WebSocket]] = defaultdict(set)
        self._verrou = asyncio.Lock()

    async def abonner(self, canal: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._verrou:
            self._abonnes[canal].add(ws)

    async def desabonner(self, canal: str, ws: WebSocket) -> None:
        async with self._verrou:
            self._abonnes.get(canal, set()).discard(ws)
            if not self._abonnes.get(canal):
                self._abonnes.pop(canal, None)

    async def diffuser(self, canal: str, message: dict) -> None:
        """Envoie `message` (JSON) à tous les abonnés d'un canal. Les sockets morts sont purgés."""
        async with self._verrou:
            cibles = list(self._abonnes.get(canal, set()))
        morts = []
        for ws in cibles:
            try:
                await ws.send_json(message)
            except Exception:
                morts.append(ws)
        if morts:
            async with self._verrou:
                for ws in morts:
                    self._abonnes.get(canal, set()).discard(ws)

    @staticmethod
    def canal_cuisine(restaurant_id: str) -> str:
        return f"cuisine:{restaurant_id}"

    @staticmethod
    def canal_table(table_id: str) -> str:
        return f"table:{table_id}"


diffuseur = Diffuseur()
