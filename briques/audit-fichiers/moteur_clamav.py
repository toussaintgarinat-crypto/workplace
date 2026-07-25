"""Moteur antivirus — parle le protocole clamd (INSTREAM) à un démon ClamAV externe.

Logique adaptée de scanners/clamav.py (suitenumerique/file-scanner, MIT, ANCT/DINUM) :
même protocole, même philosophie de verdict (« jamais propre si le fichier n'a pas été
scanné en entier » — un ERROR clamd n'est PAS un verdict propre). Simplifié pour
Workplace : un seul moteur (ClamAV), pas de pool multi-hôtes ni de sélection
catégories/exav/jcop (YAGNI mono-tenant, cf. plan S195 Risque R7)."""
from __future__ import annotations

import os
from dataclasses import dataclass

import clamd

CLAMAV_HOSTS = os.getenv("CLAMAV_HOSTS", "localhost:3310")
CLAMAV_TIMEOUT = int(os.getenv("CLAMAV_TIMEOUT", "60"))

# Fragments d'erreur clamd/OS génuinement transitoires (retry utile côté appelant) —
# repris tel quel de _TRANSIENT_HINTS amont, mais ici on ne retente jamais nous-mêmes
# (scan synchrone, pas de file d'attente, cf. Risque R2) : on remonte MoteurIndisponible
# dans tous les cas, l'appelant décide s'il redemande.


class MoteurIndisponible(Exception):
    """Le démon ClamAV est injoignable, ou n'a pas pu scanner le fichier en entier."""


@dataclass
class Verdict:
    propre: bool
    raison: str | None = None


def _client():
    """Un client clamd frais (pas de pool multi-hôtes — un seul hôte configuré,
    contrairement à l'amont qui équilibre entre plusieurs)."""
    host, _, port = CLAMAV_HOSTS.split(",")[0].strip().partition(":")
    return clamd.ClamdNetworkSocket(host=host, port=int(port or 3310), timeout=CLAMAV_TIMEOUT)


def ping() -> bool:
    try:
        return _client().ping() == "PONG"
    except Exception:
        return False


def scanner(fileobj) -> Verdict:
    """Scanne un flux binaire. Lève MoteurIndisponible si le démon est injoignable ou
    si le scan n'a pas pu être mené à terme — jamais un verdict "propre" dans ce cas
    (fail-closed, cf. plan S195 Risque R6)."""
    try:
        resultat = _client().instream(fileobj)
    except (clamd.ConnectionError, ConnectionRefusedError, OSError) as exc:
        raise MoteurIndisponible(f"ClamAV injoignable : {exc}") from exc
    statut, raison = resultat["stream"]
    if statut == "OK":
        return Verdict(propre=True)
    if statut == "ERROR":
        raise MoteurIndisponible(f"scan non mené à terme : {raison}")
    return Verdict(propre=False, raison=raison)   # FOUND (détection)
