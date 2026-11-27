"""Harnais de conformité du contrat de données (S248) — réutilisable par toute app candidate.

L'app fournit un ADAPTATEUR (souvent un client de test HTTP) :
    peupler(u)                -> crée des données pour l'utilisateur u
    exporter(u)               -> octets du paquet
    etat(u)                   -> (comptages: dict, empreinte: str) de l'état courant de u
    reinitialiser(u, empreinte) -> remet u à zéro ; lève Refus si l'empreinte ≠ état courant
    importer(u, octets)       -> réinjecte ; lève Refus si le paquet est refusé
`Refus` = l'app a répondu par un refus (HTTP 4xx). Toute violation lève AssertionError.
"""


class Refus(Exception):
    """L'app refuse l'opération (à lever par l'adaptateur sur un refus applicatif)."""


def _doit_refuser(f, message):
    try:
        f()
    except Refus:
        return
    raise AssertionError(message)


def _altere(octets: bytes) -> bytes:
    milieu = len(octets) // 2
    return octets[:milieu] + bytes([octets[milieu] ^ 0xFF]) + octets[milieu + 1:]


def verifier_conformite(a, u1: str = "claire", u2: str = "marina") -> None:
    a.peupler(u1)
    a.peupler(u2)
    avant_u1, avant_u2 = a.etat(u1), a.etat(u2)
    assert sum(avant_u1[0].values()) > 0, "peupler() doit créer des données"
    assert avant_u1 != avant_u2, "les deux utilisateurs doivent avoir des données distinctes"

    paquet = a.exporter(u1)

    # Garde-fous : refus d'un reset sans empreinte exacte, d'un paquet falsifié ou étranger.
    _doit_refuser(lambda: a.reinitialiser(u1, "empreinte-fausse"),
                  "reinitialiser doit refuser une empreinte qui ne correspond pas")
    assert a.etat(u1) == avant_u1, "un reset refusé ne doit rien modifier"
    _doit_refuser(lambda: a.importer(u1, _altere(paquet)),
                  "importer doit refuser un paquet falsifié")
    _doit_refuser(lambda: a.importer(u2, paquet),
                  "importer doit refuser le paquet d'un autre utilisateur")
    assert a.etat(u2) == avant_u2, "un import refusé ne doit rien modifier"

    # Séquence nominale + isolation.
    a.reinitialiser(u1, avant_u1[1])
    assert sum(a.etat(u1)[0].values()) == 0, "après reset, l'espace de u1 doit être vide"
    assert a.etat(u2) == avant_u2, "le reset de u1 ne doit PAS toucher u2"
    a.importer(u1, paquet)
    assert a.etat(u1) == avant_u1, "export→reset→import doit redonner un état identique"
    assert a.etat(u2) == avant_u2, "l'import de u1 ne doit PAS toucher u2"
