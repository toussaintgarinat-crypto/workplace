"""Filtre de pseudo/nom de personnage — liste statique de mots bannis (V1, décision de
cadrage anti-abus : pas de file de modération, pas de recours humain). Liste courte,
volontairement non exhaustive — à enrichir opérationnellement si besoin.

Deux registres : substring pour les mots assez longs pour ne jamais apparaître
innocemment dans un mot réel ; frontière de mot (regex) pour les mots courts qui, en
substring nu, produiraient de faux positifs sur des mots/prénoms français ordinaires
("nique" dans "Dominique", "pute" dans "dispute"/"réputée"/"amputée")."""
import re

MOTS_BANNIS = {
    "connard", "connasse", "salope", "encule", "enculé",
    "nazi", "hitler", "batard", "bâtard",
}
MOTS_BANNIS_FRONTIERE = {"nique", "pute"}

_PATTERN_FRONTIERE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in MOTS_BANNIS_FRONTIERE) + r")\b",
    re.IGNORECASE,
)


def contient_mot_banni(texte: str) -> bool:
    minuscule = texte.lower()
    if any(mot in minuscule for mot in MOTS_BANNIS):
        return True
    return bool(_PATTERN_FRONTIERE.search(texte))
