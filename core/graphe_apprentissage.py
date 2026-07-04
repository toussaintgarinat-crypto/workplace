"""Graphe d'apprentissage bipartite mémoires ↔ capacités (S145).

Relie les entrées de la brique mémoire (5600) aux capacités du Cœur via chevauchement
lexical. Sert de second signal dans routage_outils.py : les capacités co-citées avec
des souvenirs pertinents reçoivent un boost de score avant le tri final.

Inspiré de learning_graph.py (Hermes Agent, Nous Research, MIT).
Tout en mémoire vive — aucune persistance, aucune base de données.
"""
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "en", "et", "ou",
    "je", "tu", "il", "nous", "vous", "ils", "que", "qui", "ce", "se",
    "est", "sont", "avec", "pour", "sur", "dans", "par", "au", "aux",
    "the", "a", "an", "of", "in", "to", "and", "or", "is", "are",
}
LONGUEUR_MIN_TERME = 3


def _termes(texte: str) -> set[str]:
    mots = re.findall(r"[a-zàâéèêëîïôùûüç_]+", texte.lower())
    return {m for m in mots if len(m) >= LONGUEUR_MIN_TERME and m not in STOPWORDS}


def _nom_spec(spec: dict) -> str:
    """Nom d'une capacité — supporte le format plat {name} et le format function-calling."""
    return spec.get("name") or (spec.get("function") or {}).get("name", "")


def _desc_spec(spec: dict) -> str:
    return spec.get("description") or (spec.get("function") or {}).get("description", "")


@dataclass
class GrapheApprentissage:
    # capacite_nom → score de boost normalisé (0–1)
    _boost: dict[str, float] = field(default_factory=dict)
    # capacite_nom → set de termes co-occurrents (pour debug et calcul de couverture)
    _termes_lies: dict[str, set] = field(default_factory=dict)
    _construit: bool = False

    def construire(self, souvenirs: list[str], specs_capacites: list[dict]) -> None:
        """Construit le graphe lexical depuis une liste de souvenirs et de specs d'outils.

        souvenirs : textes bruts issus de la brique mémoire
        specs_capacites : dicts avec {"name", "description"} OU format function-calling
        """
        self._boost.clear()
        self._termes_lies.clear()

        # Index inversé : terme → noms de capacités qui le contiennent
        index_capacites: dict[str, set[str]] = {}
        for spec in specs_capacites:
            nom = _nom_spec(spec)
            desc = _desc_spec(spec)
            for t in _termes(nom):
                index_capacites.setdefault(t, set()).add(nom)
            for t in _termes(desc):
                index_capacites.setdefault(t, set()).add(nom)

        # Pour chaque souvenir, accumule le poids des capacités co-citées
        for souvenir in souvenirs:
            termes_sou = _termes(souvenir)
            for terme in termes_sou:
                for cap in index_capacites.get(terme, set()):
                    # Bonus × 2 si le terme est dans le NOM de la capacité (signal fort)
                    bonus = 2.0 if terme in _termes(cap) else 1.0
                    self._boost[cap] = self._boost.get(cap, 0.0) + bonus
                    self._termes_lies.setdefault(cap, set()).add(terme)

        # Normalisation entre 0 et 1
        if self._boost:
            max_score = max(self._boost.values())
            if max_score > 0:
                self._boost = {k: v / max_score for k, v in self._boost.items()}

        self._construit = True

    def boost(self, requete: str, specs_capacites: list[dict]) -> dict[str, float]:
        """Scores de boost {nom_capacite: score} pour les capacités co-citées avec la requête."""
        if not self._construit:
            return {}
        termes_req = _termes(requete)
        scores: dict[str, float] = {}
        for spec in specs_capacites:
            nom = _nom_spec(spec)
            if nom not in self._boost:
                continue
            termes_lies = self._termes_lies.get(nom, set())
            intersection = termes_req & termes_lies
            if not intersection:
                continue
            couverture = len(intersection) / max(len(termes_lies), 1)
            scores[nom] = self._boost[nom] * couverture
        return scores

    def stats(self) -> dict:
        return {
            "capacites_liees": len(self._boost),
            "top5": sorted(self._boost.items(), key=lambda x: -x[1])[:5],
        }


# Singleton module-level — reconstruit au démarrage, jamais persisté sur disque
_graphe = GrapheApprentissage()


async def charger_graphe(specs_capacites: list[dict]) -> None:
    """Récupère les souvenirs de la brique mémoire et reconstruit le graphe lexical."""
    memoire_url = os.getenv("MEMOIRE_URL", "http://memoire:5600")
    memoire_key = os.getenv("MEMOIRE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{memoire_url}/souvenirs",
                headers={"Authorization": f"Bearer {memoire_key}"},
                params={"limite": 200},
            )
            r.raise_for_status()
            souvenirs = [
                (e.get("contenu") or e.get("titre") or "")
                for e in r.json().get("souvenirs", [])
            ]
    except Exception:  # noqa: BLE001 — brique absente = graphe vide, pas de crash
        souvenirs = []
    _graphe.construire(souvenirs, specs_capacites)
    logger.info(
        "Graphe apprentissage : %d capacités liées depuis %d souvenirs",
        len(_graphe._boost), len(souvenirs),
    )
