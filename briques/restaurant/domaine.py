"""Sous-domaine CŒUR du service à table (DDD pragmatique, dans la brique).

Ce module est **PUR** : aucune I/O, aucune dépendance à SQLite ou FastAPI. Il porte le
langage ubiquitaire (Argent, Convive, …) et les invariants de calcul, testables en
microsecondes. Les repositories (`stockage.py`) et la couche interface (`main.py`)
s'appuient dessus. On introduit les agrégats/objets-valeur AU FIL DE L'EAU (S81→S83) :
ici on pose l'objet-valeur `Argent`, l'entité `Convive` et le groupage d'une commande
multi-convive (« pour qui » par ligne).
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Objet-valeur : Argent ────────────────────────────────────────
@dataclass(frozen=True)
class Argent:
    """Montant monétaire en CENTIMES + devise. Immuable (objet-valeur).

    On reste en entiers (centimes) pour éviter les flottants : un euro = 100. Les
    opérations exigent la même devise (on ne mélange pas EUR et USD par accident)."""

    cents: int
    devise: str = "EUR"

    def __post_init__(self) -> None:
        # Normalise : centimes entiers, devise en majuscules.
        object.__setattr__(self, "cents", int(self.cents))
        object.__setattr__(self, "devise", (self.devise or "EUR").upper())

    @classmethod
    def zero(cls, devise: str = "EUR") -> "Argent":
        return cls(0, devise)

    def _meme_devise(self, autre: "Argent") -> None:
        if self.devise != autre.devise:
            raise ValueError(f"Devises incompatibles : {self.devise} ≠ {autre.devise}")

    def plus(self, autre: "Argent") -> "Argent":
        self._meme_devise(autre)
        return Argent(self.cents + autre.cents, self.devise)

    def fois(self, n: int) -> "Argent":
        return Argent(self.cents * int(n), self.devise)

    def borne_positif(self) -> "Argent":
        """Jamais négatif (ex. un « reste à payer » ne descend pas sous 0)."""
        return self if self.cents >= 0 else Argent.zero(self.devise)

    def __add__(self, autre: "Argent") -> "Argent":
        return self.plus(autre)


# ── Entité : Convive ─────────────────────────────────────────────
@dataclass(frozen=True)
class Convive:
    """Une personne attablée. Identifiée par son nom (prénom ou place « A/B/C »).

    Le nom est l'identité dans une session : c'est lui qui porte la part d'addition.
    Vide → « Convive » (jamais d'attribution anonyme cassée)."""

    nom: str

    @classmethod
    def normaliser(cls, brut: str | None, defaut: str = "Convive") -> str:
        """Nettoie un nom de convive. Source unique de la règle (back + front s'alignent)."""
        return (brut or "").strip() or defaut


# ── Service de domaine : groupage d'une commande multi-convive ───
def grouper_par_convive(plats: list | None, convive_defaut: str = "") -> list[tuple[str, list]]:
    """Range les lignes d'un panier PAR convive, en conservant l'ordre d'apparition.

    Chaque item peut porter son propre `convive` (« pour qui » choisi à l'ajout) ; sinon
    on retombe sur `convive_defaut`. Retourne [(convive, [items]), …] → le repository créera
    UNE commande par convive (la cuisine reste groupée par personne). Pur, sans I/O."""
    groupes: dict[str, list] = {}
    ordre: list[str] = []
    for item in plats or []:
        conv = Convive.normaliser(item.get("convive"), Convive.normaliser(convive_defaut))
        if conv not in groupes:
            groupes[conv] = []
            ordre.append(conv)
        groupes[conv].append(item)
    return [(conv, groupes[conv]) for conv in ordre]
