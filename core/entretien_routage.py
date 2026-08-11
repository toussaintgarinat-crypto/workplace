"""Routage structurel des tours d'un entretien guidé actif (S228) vers Forge.

Tant qu'un entretien Forge (venture d'audit) est `en_cours` pour un fil de conversation,
les tours ne passent PAS par le LLM/tool-calling habituel : ils sont routés directement
vers `POST /ventures/{id}/entretien/repondre`. Ça évite deux écueils : le LLM qui oublie
d'appeler l'outil, et le coût d'un tour de function-calling pour chaque réponse d'entretien.

Clé du registre = `accord_action.cle(fil, utilisateur)` (le MÊME motif que le gate d'action,
S222) : le fil seul ne suffit pas, deux personnes sur le même fil web ne doivent jamais
partager le même entretien actif.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Mots-clés EXPLICITES de pause. Volontairement court et ancré sur des frontières de mots —
# même philosophie que `accord_action._REFUS` : un faux positif ne coûte qu'une relance
# évitable, un faux négatif laisse l'entretien actif (état jamais perdu, juste pas
# repris automatiquement ce tour-ci). La détection d'un « changement de sujet clair » au
# sens large (spec S228) est volontairement hors scope de ce mot-clé — trop ambigu pour
# une regex fiable ; le dirigeant garde la main via ces mots-clés explicites.
_PAUSE = re.compile(r"\b(pause|on reprendra|plus tard|reprendrons)\b")


def _sans_accents(texte: str) -> str:
    plie = unicodedata.normalize("NFD", texte or "").casefold()
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def est_pause(message: str) -> bool:
    return bool(_PAUSE.search(_sans_accents(message)))


@dataclass
class Registre:
    """Entretiens actifs, indexés par `fil_accord` (= `accord_action.cle(fil, utilisateur)`)."""

    _actifs: dict[str, str] = field(default_factory=dict)  # fil_accord -> venture_id

    def activer(self, fil_accord: str, venture_id: str) -> None:
        self._actifs[fil_accord] = venture_id

    def actif(self, fil_accord: str) -> str | None:
        return self._actifs.get(fil_accord)

    def desactiver(self, fil_accord: str) -> None:
        self._actifs.pop(fil_accord, None)


REGISTRE = Registre()


async def repondre(registre, fil_accord: str, venture_id: str, message: str, client,
                   base_forge: str) -> dict:
    """Appelle Forge `/entretien/repondre` et désactive le registre si l'entretien se
    termine (clôture naturelle du squelette). `registre` (catalogue Cœur) n'est pas utilisé
    ici mais gardé dans la signature pour cohérence avec le reste du fichier appelant.

    Auto-guérison sur erreur HTTP (revue finale S228, Finding I1) : sans lire
    `status_code`, un 4xx/5xx laissait `data.get("statut")` à None, donc PAS "termine",
    donc le registre restait actif — et comme le routage structurel court-circuite le LLM
    tant qu'il est actif, le fil était confisqué pour de bon (« D'accord, continuons. » à
    chaque tour, sans autre issue qu'un mot-clé de pause explicite). Ça arrive pour de
    vrai : entretien clôturé hors bande, Forge redémarré, venture supprimée.
    On désactive donc le registre et on rend une charge que `_flux_entretien` sait
    afficher honnêtement — mieux vaut rendre la main au LLM que boucler.
    """
    r = await client.post(f"{base_forge}/ventures/{venture_id}/entretien/repondre",
                          json={"message": message})
    if r.status_code >= 400:
        REGISTRE.desactiver(fil_accord)
        return {"statut": "interrompu", "erreurHttp": r.status_code, "question": None}
    data = r.json()
    if data.get("statut") == "termine":
        REGISTRE.desactiver(fil_accord)
    return data
