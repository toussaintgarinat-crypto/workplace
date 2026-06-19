"""Moteur de SYNTHÈSE VOCALE PROVIDER-AGNOSTIQUE — orchestrateur (miroir transcription).

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence
(SOUVERAIN `piper` d'abord) et on retient le PREMIER audio obtenu.

Repli HONNÊTE : si AUCUN fournisseur n'est configuré, ou si tous échouent (binaire absent /
modèle manquant / clé invalide / timeout), on rend un résultat SANS audio qui le DIT
(`place_holder: true`, note explicite). On ne casse jamais l'appelant, et on ne fabrique
JAMAIS de fausse voix : mieux vaut un « moteur absent » assumé qu'un audio bidon.
"""
from typing import Optional

import fournisseurs


async def fournisseur_actif() -> Optional[str]:
    """Premier fournisseur réellement utilisable (pour /sante). La présence de la
    clé/binaire suffit — on ne lance pas une synthèse juste pour un état de santé."""
    dispo = fournisseurs.disponibles()
    return dispo[0] if dispo else None


def _repli(note: str, candidats: list, erreurs: dict | None = None) -> dict:
    res = {"audio": None, "format": None, "backend": "placeholder", "place_holder": True,
           "note": note, "fournisseurs": candidats}
    if erreurs:
        res["erreurs"] = erreurs
    return res


async def synthetiser(texte: str, voix: Optional[str] = None, langue: Optional[str] = None,
                      format: Optional[str] = None, fournisseur: Optional[str] = None) -> dict:
    """Vocalise `texte`. Rend un dict normalisé :

        {audio: bytes|None, format, voix, backend, place_holder}

    `voix` (optionnel) choisit la voix/modèle ; `langue` (optionnel) la langue ;
    `format` (optionnel) le format audio souhaité (opus/mp3/wav…) ;
    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    """
    if not (texte or "").strip():
        return _repli("Texte vide.", [])

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Fournisseur « {fournisseur} » indisponible" if fournisseur
                else "Aucun moteur de synthèse vocale configuré (installe Piper + PIPER_VOICE "
                     "pour le souverain, ou pose une clé hébergée)")
        return _repli(note, candidats)

    erreurs = {}
    for nom in candidats:
        try:
            audio, fmt = await fournisseurs.REGISTRE[nom].synthetiser(texte, voix, langue, format)
            if audio:
                return {"audio": audio, "format": fmt, "voix": voix,
                        "backend": nom, "place_holder": False}
            erreurs[nom] = "aucun audio renvoyé"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return _repli("Moteurs essayés sans succès : " + ", ".join(candidats), candidats, erreurs)
