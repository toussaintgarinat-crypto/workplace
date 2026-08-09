"""Format d'exposition Prometheus, sans dépendance (S225).

Pourquoi pas `prometheus_client` : le parc épingle ses dépendances brique par brique
(`constraints-workplace.txt`), et le format texte tient en cinquante lignes. Ajouter une
bibliothèque à 39 images pour concaténer des chaînes ne se justifie pas.

Usage dans une brique :

    from shared.metriques import Registre

    @app.get("/metrics")
    def metrics():
        r = Registre()
        r.jauge("workplace_truc_age_secondes", 42, {"brique": "mail"},
                aide="Âge du dernier succès.")
        return Response(r.rendu(), media_type=Registre.TYPE_MIME)

Deux règles que ce module fait respecter, parce qu'elles sont la cause n°1 de métriques
inexploitables :

1. **`# HELP`/`# TYPE` une seule fois par nom**, même si la métrique porte vingt étiquettes.
   Prometheus rejette silencieusement un bloc dupliqué.
2. **Les valeurs d'étiquette sont échappées.** Un nom de brique ou de tâche vient d'un
   manifeste écrit à la main : un guillemet ou un antislash dedans casserait le parsing.
"""

from __future__ import annotations

import math

TYPE_MIME = "text/plain; version=0.0.4; charset=utf-8"


def _echapper(valeur: str) -> str:
    return (str(valeur).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n"))


def _nombre(v) -> str:
    """Rend une valeur au format Prometheus. NaN/inf sont des valeurs légales du format
    (et bien plus honnêtes qu'un 0 inventé pour « on ne sait pas »)."""
    f = float(v)
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "+Inf" if f > 0 else "-Inf"
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


class Registre:
    """Accumule des points de mesure puis rend le texte d'exposition."""

    TYPE_MIME = TYPE_MIME

    def __init__(self) -> None:
        self._entetes: dict[str, tuple[str, str]] = {}   # nom → (type, aide)
        self._points: dict[str, list[str]] = {}          # nom → lignes

    def _ajouter(self, nom: str, type_: str, valeur, etiquettes: dict | None,
                 aide: str | None) -> None:
        if nom not in self._entetes:
            self._entetes[nom] = (type_, aide or nom)
            self._points[nom] = []
        rendu_etiq = ""
        if etiquettes:
            rendu_etiq = "{" + ",".join(
                f'{c}="{_echapper(v)}"' for c, v in sorted(etiquettes.items())
                if v is not None) + "}"
        self._points[nom].append(f"{nom}{rendu_etiq} {_nombre(valeur)}")

    def jauge(self, nom: str, valeur, etiquettes: dict | None = None,
              aide: str | None = None) -> None:
        """Valeur qui monte ET descend (âge, ratio, effectif)."""
        self._ajouter(nom, "gauge", valeur, etiquettes, aide)

    def compteur(self, nom: str, valeur, etiquettes: dict | None = None,
                 aide: str | None = None) -> None:
        """Valeur qui ne fait que croître (total d'appels, d'échecs).

        ⚠ Par convention Prometheus le nom se termine par `_total`, et un redémarrage
        remet à zéro — c'est attendu, `rate()` sait le gérer."""
        self._ajouter(nom, "counter", valeur, etiquettes, aide)

    def rendu(self) -> str:
        blocs = []
        for nom in sorted(self._entetes):
            type_, aide = self._entetes[nom]
            # `# HELP` tient sur UNE ligne : un texte d'aide multi-ligne (docstring
            # recopiée un peu vite) casserait le parsing de tout ce qui suit.
            aide = str(aide).replace("\\", "\\\\").replace("\n", " ").strip()
            blocs.append(f"# HELP {nom} {aide}")
            blocs.append(f"# TYPE {nom} {type_}")
            blocs.extend(sorted(self._points[nom]))
        return "\n".join(blocs) + "\n"
