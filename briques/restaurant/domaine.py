"""Sous-domaine CŒUR du service à table (DDD pragmatique, dans la brique).

Ce module est **PUR** : aucune I/O, aucune dépendance à SQLite ou FastAPI. Il porte le
langage ubiquitaire (Argent, Convive, …) et les invariants de calcul, testables en
microsecondes. Les repositories (`stockage.py`) et la couche interface (`main.py`)
s'appuient dessus. On introduit les agrégats/objets-valeur AU FIL DE L'EAU (S81→S83) :
ici on pose l'objet-valeur `Argent`, l'entité `Convive` et le groupage d'une commande
multi-convive (« pour qui » par ligne).
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

# Longueur du code partagé d'une tablée (PIN à 4 chiffres, façon code Wi-Fi : court à
# dicter à voisin de table, jetable — il ne protège qu'une addition en cours).
LONGUEUR_PIN = 4


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


# ── Agrégat racine : SessionDeTable ──────────────────────────────
@dataclass(frozen=True)
class SessionDeTable:
    """La tablée qui partage UNE addition à un instant donné (agrégat racine du service
    à table). Identité = (table, numéro de session) ; `numero` = compteur incrémenté à
    chaque clôture → une nouvelle tablée = une nouvelle session, l'ancienne est archivée
    en ticket. Plusieurs appareils peuvent partager la même session.

    `code_pin` (optionnel) protège l'addition en cours : tant qu'il est posé, un appareil
    doit le présenter pour REJOINDRE la table (commander / régler / voir l'addition).
    `None` = table OUVERTE (défaut historique : tout scan du QR rejoint directement, aucun
    code) — on ne casse pas l'existant, le PIN est un réglage opt-in du restaurateur."""

    table_id: str
    numero: int
    code_pin: str | None = None

    @property
    def demarree(self) -> bool:
        """Vrai si un 1er appareil a DÉMARRÉ la session (un PIN protège déjà l'addition)."""
        return bool(self.code_pin)

    def autorise(self, pin_saisi: str | None) -> bool:
        """Un appareil peut rejoindre si la session n'exige aucun code (table ouverte) OU si
        le PIN saisi correspond. Comparaison à temps constant (anti-timing). Fail-closed :
        un PIN attendu mais vide/incorrect → refus."""
        if not self.code_pin:
            return True
        return hmac.compare_digest(str(pin_saisi or ""), str(self.code_pin))


# ── Service de domaine : répartition flexible de l'addition (S83) ─
def parts_egales(total_cents: int, parts: int) -> list[int]:
    """Partage `total_cents` en `parts` PARTS ÉGALES, en centimes, somme EXACTE.

    Le résidu (centimes non divisibles) est étalé sur les PREMIÈRES parts → personne
    ne paie un centime de plus que nécessaire et le total tombe juste (jamais 3×3,33 €
    pour 10 € qui laisserait 1 centime orphelin). Ex. 1000/3 → [334, 333, 333].
    Pur, sans I/O. `parts` ≥ 1 (sinon 1 part = le tout) ; total négatif borné à 0."""
    parts = max(1, int(parts))
    total = max(0, int(total_cents))
    base, residu = divmod(total, parts)
    return [base + (1 if i < residu else 0) for i in range(parts)]


def montant_a_encaisser(reste_global_cents: int, mode: str, *, du_convive_cents: int = 0,
                        total_cents: int = 0, parts: int = 0, montant_cents: int = 0) -> int:
    """Calcule, côté SERVEUR, le montant réellement encaissable pour un paiement, selon le
    `mode` de répartition, TOUJOURS borné au reste GLOBAL de la table (anti-surpaiement :
    on n'encaisse jamais plus que ce qui reste dû à la table, peu importe le mode).

    - `part`    : la part propre du convive (« chacun ses plats », défaut historique).
    - `egal`    : une part d'un partage égal du TOTAL en `parts` (la plus grosse part ;
                  le dernier payeur règle le reliquat, plus petit → somme exacte).
    - `libre`   : un montant arbitraire choisi par le payeur (« je mets 30 € »).
    - `tournee` : TOUT le reste de la table d'un coup (« je paye ma tournée » : un convive
                  régale toute la tablée). Égal au reste global, donc solde la table.

    Retourne le montant borné (≥ 0). 0 → rien à encaisser (déjà soldé / saisie vide)."""
    reste = max(0, int(reste_global_cents))
    if reste <= 0:
        return 0
    if mode == "egal":
        vise = parts_egales(total_cents, parts)[0] if parts else 0
    elif mode == "libre":
        vise = max(0, int(montant_cents))
    elif mode == "tournee":           # « je paye ma tournée » : tout le reste de la table
        vise = reste
    else:  # "part" (défaut) — le reste dû propre au convive
        vise = max(0, int(du_convive_cents))
    return min(vise, reste)


# ── Objet-valeur : Note d'avis (1 à 5 étoiles) ───────────────────
NOTE_MIN, NOTE_MAX = 1, 5


def normaliser_note(brut) -> int | None:
    """Valide une note d'avis : un entier **borné à 1–5 étoiles**. Source unique de la règle
    (back + front s'alignent). Retourne None si la saisie n'est pas convertible (≠ « note 0 »
    silencieuse) → l'appelant refuse explicitement. Un float (4.0) est accepté et tronqué."""
    try:
        n = int(brut)
    except (TypeError, ValueError):
        return None
    if n < NOTE_MIN or n > NOTE_MAX:
        return None
    return n


def moyenne_notes(notes: list[int] | None) -> float:
    """Moyenne d'une liste de notes, arrondie à **une décimale** (ex. 4.3). Liste vide → 0.0
    (pas de division par zéro, et « aucun avis » se lit comme 0). Pur, sans I/O."""
    notes = [n for n in (notes or []) if n is not None]
    if not notes:
        return 0.0
    return round(sum(notes) / len(notes), 1)


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
