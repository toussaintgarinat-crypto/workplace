"""Guardrails outils du Cœur (Sprint S143, étendu S221).

Protège la boucle d'inférence contre les appels d'outils répétitifs :
- même outil + mêmes args en erreur répétée → warn puis block
- résultat identique tour après tour (lecture circulaire) → warn puis block
- arguments non conformes au manifeste → block AVANT tout appel réseau (S221)

Instance par conversation (jamais en global) : aucune fuite entre sessions.

S221 : le validateur est injecté (`valideur`), pas importé — ce module reste une machine à
états sans dépendance, et les tests peuvent le piloter sans registre ni manifest. Un
validateur qui lève est ignoré : un garde-fou ne casse jamais un tour.
"""

import json
import os
from dataclasses import dataclass, field
from hashlib import sha256


@dataclass
class Config:
    seuil_warn_echecs_identiques: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_WARN_ECHECS", "2")))
    seuil_block_echecs_identiques: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_BLOCK_ECHECS", "4")))
    seuil_warn_resultat_identique: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_WARN_IDENTIQUE", "3")))
    seuil_block_resultat_identique: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_BLOCK_IDENTIQUE", "5")))
    seuil_warn_echecs_meme_outil: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_WARN_OUTIL", "3")))
    seuil_block_echecs_meme_outil: int = field(
        default_factory=lambda: int(os.getenv("GUARDRAIL_SEUIL_BLOCK_OUTIL", "6")))


@dataclass
class Guardrail:
    config: Config = field(default_factory=Config)
    # S221 : (nom, args) → liste d'écarts (objets portant `.bloquant` et `.message`).
    # None = validation désactivée (comportement S143 strictement inchangé).
    valideur: object = None
    _echecs_identiques: dict = field(default_factory=dict)   # cle → nb échecs identiques
    _echecs_outil: dict = field(default_factory=dict)        # nom → nb échecs totaux
    _resultats: dict = field(default_factory=dict)           # cle → {hash, n}
    _ecarts_vus: list = field(default_factory=list)          # catégories, pour le comptage

    def _cle(self, nom: str, args: dict) -> str:
        return sha256(f"{nom}:{json.dumps(args, sort_keys=True, default=str)}".encode()).hexdigest()[:16]

    def _valider(self, nom: str, args: dict) -> list:
        if self.valideur is None:
            return []
        try:
            ecarts = list(self.valideur(nom, args) or [])
        except Exception:  # noqa: BLE001 — un garde-fou ne casse jamais un tour
            return []
        self._ecarts_vus.extend(getattr(e, "categorie", "?") for e in ecarts)
        return ecarts

    def ecarts_par_categorie(self) -> dict:
        """Comptage des écarts de validation vus dans cette conversation (S221).

        Sans cette mesure, on ne saura pas si le LLM se trompe d'ARGUMENTS (la validation
        unitaire suffit) ou d'ENCHAÎNEMENT (il faudrait un plan explicite — cf. S226)."""
        out: dict = {}
        for c in self._ecarts_vus:
            out[c] = out.get(c, 0) + 1
        return out

    def before_call(self, nom: str, args: dict) -> tuple[str, str | None]:
        """Décide si l'appel peut avoir lieu. Retourne (action, message).
        action ∈ allow | warn | block | halt.

        S221 : les écarts au manifeste passent AVANT les compteurs d'échec — quand les deux
        s'appliquent on bloque de toute façon, autant rendre le message corrigeable."""
        ecarts = self._valider(nom, args)
        bloquants = [e for e in ecarts if getattr(e, "bloquant", False)]
        if bloquants:
            details = " ; ".join(e.message for e in bloquants)
            return "block", (f"Appel `{nom}` non conforme au manifeste — {details}. "
                             "Corrige les arguments et rappelle l'outil.")

        cle = self._cle(nom, args)
        n_id = self._echecs_identiques.get(cle, 0)
        n_outil = self._echecs_outil.get(nom, 0)
        c = self.config
        if n_id >= c.seuil_block_echecs_identiques:
            return "block", f"Outil `{nom}` a échoué {n_id}× avec ces arguments — arrêté."
        if n_outil >= c.seuil_block_echecs_meme_outil:
            return "block", f"Outil `{nom}` a échoué {n_outil}× consécutivement — arrêté."
        if n_id >= c.seuil_warn_echecs_identiques:
            return "warn", f"Outil `{nom}` déjà en échec {n_id}× avec ces arguments."
        if n_outil >= c.seuil_warn_echecs_meme_outil:
            return "warn", f"Outil `{nom}` a déjà échoué {n_outil}× — tenter une autre approche."
        if ecarts:  # non bloquants (param inconnu, éléments de tableau) : on laisse passer
            return "warn", " ; ".join(e.message for e in ecarts)
        return "allow", None

    def after_call(self, nom: str, args: dict, resultat: str, *, erreur: bool = False):
        """Met à jour les compteurs après un appel (succès ou échec)."""
        cle = self._cle(nom, args)
        if erreur:
            self._echecs_identiques[cle] = self._echecs_identiques.get(cle, 0) + 1
            self._echecs_outil[nom] = self._echecs_outil.get(nom, 0) + 1
        else:
            self._echecs_identiques.pop(cle, None)
            self._echecs_outil.pop(nom, None)
            h = sha256(resultat.encode()).hexdigest()
            prev = self._resultats.get(cle)
            if prev and prev["hash"] == h:
                prev["n"] += 1
            else:
                self._resultats[cle] = {"hash": h, "n": 1}

    def verifier_idempotence(self, nom: str, args: dict) -> tuple[str, str | None]:
        """Détecte les lectures circulaires (résultat identique tour après tour)."""
        cle = self._cle(nom, args)
        n = self._resultats.get(cle, {}).get("n", 0)
        c = self.config
        if n >= c.seuil_block_resultat_identique:
            return "block", f"`{nom}` retourne le même résultat depuis {n} tours — aucun progrès."
        if n >= c.seuil_warn_resultat_identique:
            return "warn", f"`{nom}` retourne le même résultat depuis {n} tours."
        return "allow", None

    def reinitialiser(self):
        self._echecs_identiques.clear()
        self._echecs_outil.clear()
        self._resultats.clear()
