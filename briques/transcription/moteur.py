"""Moteur de TRANSCRIPTION PROVIDER-AGNOSTIQUE — orchestrateur (miroir images/vidéo).

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence
(SOUVERAIN `local` d'abord) et on retient la PREMIÈRE transcription obtenue.

Repli HONNÊTE : si AUCUN fournisseur n'est configuré, ou si tous échouent (lib absente /
clé invalide / timeout), on rend un résultat VIDE qui le DIT (`place_holder: true`, texte
vide, note explicite). On ne casse jamais l'appelant, et on n'INVENTE JAMAIS de texte :
mieux vaut un « moteur absent » assumé qu'une fausse transcription.
"""
from typing import Optional

import fournisseurs


async def fournisseur_actif() -> Optional[str]:
    """Premier fournisseur réellement utilisable (pour /sante). La présence de la
    clé/lib suffit — on ne lance pas une transcription juste pour un état de santé."""
    dispo = fournisseurs.disponibles()
    return dispo[0] if dispo else None


def _repli(note: str, langue: Optional[str], candidats: list, erreurs: dict | None = None) -> dict:
    res = {"texte": "", "segments": [], "langue": langue, "diarisation": False,
           "backend": "placeholder", "place_holder": True, "note": note,
           "fournisseurs": candidats}
    if erreurs:
        res["erreurs"] = erreurs
    return res


async def transcrire(audio: bytes, nom_fichier: str = "audio.wav",
                     langue: Optional[str] = None, diarisation: bool = False,
                     fournisseur: Optional[str] = None) -> dict:
    """Transcrit `audio` (octets bruts). Rend un dict normalisé :

        {texte, segments, langue, diarisation, backend, place_holder}

    `langue` (optionnel) impose la langue ; sinon elle est détectée.
    `diarisation` demande l'identification des locuteurs (selon le fournisseur).
    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    """
    if not audio:
        return _repli("Audio vide.", langue, [])

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:
        candidats = fournisseurs.disponibles()

    if not candidats:
        note = (f"Fournisseur « {fournisseur} » indisponible" if fournisseur
                else "Aucun moteur de transcription configuré (active le local Whisper "
                     "ou pose une clé hébergée)")
        return _repli(note, langue, candidats)

    erreurs = {}
    for nom in candidats:
        try:
            res = await fournisseurs.REGISTRE[nom].transcrire(
                audio, nom_fichier, langue, diarisation)
            if res and res.get("texte", "").strip():
                return {**res, "backend": nom, "place_holder": False}
            erreurs[nom] = "aucun texte renvoyé"
        except Exception as e:  # noqa: BLE001
            erreurs[nom] = str(e)[:160]

    return _repli("Moteurs essayés sans succès : " + ", ".join(candidats),
                  langue, candidats, erreurs)
