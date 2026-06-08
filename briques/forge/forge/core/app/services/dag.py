"""Tri topologique (Kahn) — portage de ``forge/core/src/services/dag.ts`` (S132).

Référence testée du tri utilisé par ``routers/task_dag.py`` (POST /poles/:id/dag/run).
Les dépendances pointant vers un nœud absent sont ignorées (comme dans le Bun).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class DagNode:
    id: str
    dependances: list[str]


@dataclass
class TopoResult:
    order: list[str]
    cycle: bool  # True si tous les nœuds n'ont pas pu être placés


def topological_sort(nodes: list[DagNode]) -> TopoResult:
    """Kahn's algorithm — détecte les cycles (cycle=True si order < nodes)."""
    in_degree: dict[str, int] = {}
    adj: dict[str, list[str]] = {}
    for n in nodes:
        in_degree[n.id] = 0
        adj[n.id] = []
    for n in nodes:
        for dep in n.dependances:
            if dep in adj:  # dépendance vers nœud connu seulement
                adj[dep].append(n.id)
                in_degree[n.id] += 1

    queue: deque[str] = deque(n.id for n in nodes if in_degree[n.id] == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for nxt in adj[nid]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    return TopoResult(order=order, cycle=len(order) < len(nodes))
