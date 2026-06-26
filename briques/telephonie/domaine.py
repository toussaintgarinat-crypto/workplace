"""Domaine PUR de la téléphonie — AUCUNE I/O (ni réseau, ni base, ni fichier).

On modélise ici, en langage métier et testable hors-ligne, les invariants d'un canal
téléphonique : la validité d'un numéro (E.164), la longueur/segmentation d'un SMS, et les
transitions d'état autorisées d'un message et d'un appel. La couche technique (fournisseur,
stockage, HTTP) s'appuie dessus mais ne le pollue pas. Inspiré du `domaine.py` de la brique
`paiements` : le métier d'abord, pur, avant tout branchement.
"""
from __future__ import annotations

import re

# ── Statuts d'un message (SMS) ───────────────────────────────────
SMS_FILE = "file"        # accepté, en file d'envoi
SMS_ENVOYE = "envoye"    # parti (sent/delivered côté opérateur)
SMS_ECHOUE = "echoue"    # refusé / non délivré
SMS_RECU = "recu"        # entrant (reçu sur un de nos numéros)

# ── Statuts d'un appel ───────────────────────────────────────────
APPEL_INITIE = "initie"
APPEL_EN_COURS = "en_cours"
APPEL_TERMINE = "termine"
APPEL_ECHOUE = "echoue"

# Sens d'un message
SORTANT, ENTRANT = "sortant", "entrant"

# E.164 : « + » puis 1 à 15 chiffres, le premier non nul (recommandation UIT-T).
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")

# Longueur max d'un SMS concaténé (usuelle), et seuils de segmentation GSM-7.
SMS_MAX = 1600
_SEG_UNIQUE = 160        # un seul segment
_SEG_CONCAT = 153        # par segment au-delà (7 bits réservés à la concaténation)


def normaliser_numero(numero: str) -> str:
    """Nettoie (espaces, points, tirets, parenthèses) et VALIDE un numéro E.164.

    Lève `ValueError` si le résultat n'est pas un E.164 plausible — on ne laisse jamais passer
    un numéro douteux vers un fournisseur (qui le facturerait peut-être en erreur)."""
    nettoye = re.sub(r"[\s().\-]", "", numero or "")
    if not _E164.match(nettoye):
        raise ValueError(
            f"Numéro invalide (format E.164 attendu, ex. +33612345678) : {numero!r}")
    return nettoye


def numero_valide(numero: str) -> bool:
    try:
        normaliser_numero(numero)
        return True
    except ValueError:
        return False


def sms_valide(corps: str) -> bool:
    """Un SMS doit être non vide et ne pas dépasser la limite concaténée."""
    return bool(corps) and len(corps) <= SMS_MAX


def segments_sms(corps: str) -> int:
    """Nombre de segments facturés d'un SMS (1 si ≤160, sinon paquets de 153). Sert au
    coût/affichage, jamais à bloquer (on borne avant avec `sms_valide`)."""
    n = len(corps or "")
    if n == 0:
        return 0
    if n <= _SEG_UNIQUE:
        return 1
    return -(-n // _SEG_CONCAT)            # division entière par excès


_TRANSITIONS_SMS = {
    SMS_FILE: {SMS_ENVOYE, SMS_ECHOUE},
    SMS_ENVOYE: set(),
    SMS_ECHOUE: set(),
    SMS_RECU: set(),
}

_TRANSITIONS_APPEL = {
    APPEL_INITIE: {APPEL_EN_COURS, APPEL_TERMINE, APPEL_ECHOUE},
    APPEL_EN_COURS: {APPEL_TERMINE, APPEL_ECHOUE},
    APPEL_TERMINE: set(),
    APPEL_ECHOUE: set(),
}


def transition_sms_permise(actuel: str, cible: str) -> bool:
    return cible in _TRANSITIONS_SMS.get(actuel, set())


def transition_appel_permise(actuel: str, cible: str) -> bool:
    return cible in _TRANSITIONS_APPEL.get(actuel, set())
