"""Harnais de conformité du contrat de données (S248) — réutilisable par toute app candidate.

L'app fournit un ADAPTATEUR (souvent un client de test HTTP) :
    peupler(u)                  -> crée des données pour l'utilisateur u (données DISTINCTES par u)
    exporter(u)                 -> octets du paquet
    etat(u)                     -> (comptages: dict, empreinte: str) de l'état courant de u
    reinitialiser(u, empreinte) -> remet u à zéro ; lève Refus si l'empreinte ≠ état courant
    importer(u, octets)         -> réinjecte ; lève Refus si le paquet est refusé

Contrats que l'adaptateur doit respecter :
  • `Refus` = l'app a répondu par un refus (HTTP 4xx) ; il doit couvrir un paquet falsifié,
    tronqué ou corrompu (pas seulement une mauvaise signature) et un paquet d'un autre utilisateur.
  • `etat` est en lecture seule, sans effet de bord.
  • Les opérations NOMINALES ne doivent jamais lever `Refus` : le harnais le signale comme
    « refusé à tort ».
  • Une erreur qui n'est pas `Refus` (ex. 5xx, exception) se propage telle quelle : ce n'est
    pas une violation, c'est une erreur d'exécution.
  • Un refus ne doit rien modifier, y compris pour les autres utilisateurs.

Portée du harnais : il n'inspecte PAS le contenu du paquet. Un export qui perd des données
mais que l'importeur ignore silencieusement est hors de son périmètre.

Toute violation lève AssertionError (via `_exiger`, donc aussi sous `python -O`).
"""


class Refus(Exception):
    """L'app refuse l'opération (à lever par l'adaptateur sur un refus applicatif)."""


def _exiger(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _doit_refuser(f, message: str) -> None:
    try:
        f()
    except Refus:
        return
    raise AssertionError(message)


def _nominal(f, operation: str, u: str):
    try:
        return f()
    except Refus as e:
        raise AssertionError(f"{operation}({u}) refusé à tort : {e}") from e


def _altere(octets: bytes) -> bytes:
    milieu = len(octets) // 2
    return octets[:milieu] + bytes([octets[milieu] ^ 0xFF]) + octets[milieu + 1:]


def verifier_conformite(a, u1: str = "claire", u2: str = "marina") -> None:
    a.peupler(u1)
    a.peupler(u2)
    avant_u1, avant_u2 = a.etat(u1), a.etat(u2)
    _exiger(sum(avant_u1[0].values()) > 0,
            f"peupler({u1}) doit créer des données")
    _exiger(avant_u1 != avant_u2,
            "les deux utilisateurs doivent avoir des données distinctes : "
            f"{u1}={avant_u1} / {u2}={avant_u2}")

    paquet = a.exporter(u1)

    def _inchanges(quoi: str) -> None:
        apres_u1, apres_u2 = a.etat(u1), a.etat(u2)
        _exiger(apres_u1 == avant_u1,
                f"{quoi} ne doit rien modifier ({u1}) : avant={avant_u1} après={apres_u1}")
        _exiger(apres_u2 == avant_u2,
                f"{quoi} ne doit rien modifier ({u2}) : avant={avant_u2} après={apres_u2}")

    # Garde-fous : refus d'un reset sans empreinte exacte, d'un paquet falsifié, tronqué
    # ou étranger. Chaque refus doit laisser les DEUX utilisateurs intacts.
    _doit_refuser(lambda: a.reinitialiser(u1, "empreinte-fausse"),
                  "reinitialiser doit refuser une empreinte qui ne correspond pas")
    _inchanges("un reset refusé")
    _doit_refuser(lambda: a.importer(u1, _altere(paquet)),
                  "importer doit refuser un paquet falsifié")
    _inchanges("un import refusé")
    _doit_refuser(lambda: a.importer(u1, paquet[: len(paquet) // 2]),
                  "importer doit refuser un paquet tronqué")
    _inchanges("un import refusé")
    _doit_refuser(lambda: a.importer(u2, paquet),
                  "importer doit refuser le paquet d'un autre utilisateur")
    _inchanges("un import refusé")

    # Séquence nominale + isolation (aucun refus attendu).
    _nominal(lambda: a.reinitialiser(u1, avant_u1[1]), "reinitialiser", u1)
    _exiger(sum(a.etat(u1)[0].values()) == 0,
            f"après reset, l'espace de {u1} doit être vide : {a.etat(u1)}")
    _exiger(a.etat(u2) == avant_u2,
            f"le reset de {u1} ne doit PAS toucher {u2} : avant={avant_u2} après={a.etat(u2)}")
    _nominal(lambda: a.importer(u1, paquet), "importer", u1)
    _exiger(a.etat(u1) == avant_u1,
            f"export→reset→import doit redonner un état identique ({u1}) : "
            f"avant={avant_u1} après={a.etat(u1)}")
    _exiger(a.etat(u2) == avant_u2,
            f"l'import de {u1} ne doit PAS toucher {u2} : avant={avant_u2} après={a.etat(u2)}")
