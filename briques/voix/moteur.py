"""Moteur de SYNTHÈSE VOCALE PROVIDER-AGNOSTIQUE — orchestrateur (miroir transcription).

On balaie les fournisseurs DISPONIBLES (cf. fournisseurs.py) dans l'ordre de préférence
(SOUVERAIN `piper` d'abord) et on retient le PREMIER audio obtenu.

Repli HONNÊTE : si AUCUN fournisseur n'est configuré, ou si tous échouent (binaire absent /
modèle manquant / clé invalide / timeout), on rend un résultat SANS audio qui le DIT
(`place_holder: true`, note explicite). On ne casse jamais l'appelant, et on ne fabrique
JAMAIS de fausse voix : mieux vaut un « moteur absent » assumé qu'un audio bidon.
"""
from typing import Optional

import clones
import fournisseurs
import nettoyer


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


def _candidats_par_usage(texte: str, usage: Optional[str]) -> list:
    """Ordre des moteurs selon l'USAGE (« la bonne voix au bon moment ») :
      • LECTURE (texte long, ou usage forcé) → on met la voix de LECTURE en tête (résumés,
        narration : la beauté prime, la latence non) ;
      • CONVERSATION (sinon) → l'ordre habituel (voix rapide en tête).
    Le moteur de lecture n'est préposé que s'il est CHOISI et DISPONIBLE ; sinon on retombe
    proprement sur l'ordre de conversation (repli honnête, jamais d'erreur)."""
    import reglages
    base = fournisseurs.disponibles()                 # ordre conversation, moteurs dispo
    est_lecture = (usage == "lecture") or (
        usage not in ("conversation",) and len(texte) >= reglages.seuil_lecture())
    if est_lecture:
        lect = reglages.moteur_lecture()
        if lect in fournisseurs.REGISTRE and fournisseurs.REGISTRE[lect].disponible():
            return [lect] + [n for n in base if n != lect]
    return base


async def synthetiser(texte: str, voix: Optional[str] = None, langue: Optional[str] = None,
                      format: Optional[str] = None, fournisseur: Optional[str] = None,
                      usage: Optional[str] = None) -> dict:
    """Vocalise `texte`. Rend un dict normalisé :

        {audio: bytes|None, format, voix, backend, place_holder}

    `voix` (optionnel) choisit la voix/modèle ; `langue` (optionnel) la langue ;
    `format` (optionnel) le format audio souhaité (opus/mp3/wav…) ;
    `fournisseur` (optionnel) force un moteur précis ; sinon on suit l'ordre de préférence.
    `usage` (optionnel) `conversation`/`lecture` ; sinon déduit par la longueur du texte.
    """
    # Préparer POUR LA VOIX : on retire markdown/emoji/liens/code/horodatages (la voix ne les
    # dit pas), on garde tout le contenu et la ponctuation. Si rien ne reste à dire → placeholder.
    texte = nettoyer.pour_la_voix(texte or "")
    if not texte.strip():
        return _repli("Texte vide.", [])

    # Voix CLONÉE (`voix: "clone:<nom>"`) : on résout le WAV de référence et on FORCE Coqui
    # (seul moteur qui sait reproduire un timbre via speaker_wav). Repli HONNÊTE si la voix
    # clonée est inconnue (jamais un autre timbre à sa place) ou si Coqui n'est pas disponible.
    if clones.est_reference_clone(voix):
        ref = clones.resoudre(voix)
        if not ref:
            return _repli(f"Voix clonée « {voix} » introuvable dans la bibliothèque.", [])
        voix, fournisseur = ref, "coqui"

    if fournisseur:                                   # forçage explicite d'un moteur
        f = fournisseurs.REGISTRE.get(fournisseur.lower())
        candidats = [fournisseur.lower()] if (f and f.disponible()) else []
    else:                                             # routage par usage (conversation/lecture)
        candidats = _candidats_par_usage(texte, (usage or "").strip().lower() or None)

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
