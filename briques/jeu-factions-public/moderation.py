"""Filtre de pseudo/nom de personnage — liste statique de mots bannis (V1, décision de
cadrage anti-abus : pas de file de modération, pas de recours humain). Liste courte,
volontairement non exhaustive — à enrichir opérationnellement si besoin."""
MOTS_BANNIS = {
    "connard", "connasse", "salope", "pute", "encule", "enculé",
    "nazi", "hitler", "nique", "batard", "bâtard",
}


def contient_mot_banni(texte: str) -> bool:
    minuscule = texte.lower()
    return any(mot in minuscule for mot in MOTS_BANNIS)
