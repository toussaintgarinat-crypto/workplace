"""Validation des arguments d'outil contre le manifeste (S221).

`_spec_depuis_capacite` (outils.py) fabrique bien un schéma function-calling depuis le
manifeste — `type`, `requis`, `enum`… — et le donne au LLM. Mais **rien ne revérifie ce que
le LLM renvoie** : les arguments partent tels quels dans la requête HTTP vers la brique, qui
répond 422, et `_appel_dynamique` traduit ça en « Brique « X » a refusé (422) » — un message
dont le LLM ne peut RIEN faire. Résultat : un aller-retour réseau + un tour de LLM payés pour
une erreur détectable localement en microsecondes.

Ce module est le validateur pur (aucune I/O, aucun import de brique) : il compare des
arguments à un schéma et renvoie des écarts **formulés pour être corrigeables par le LLM**
(« paramètre `expediteur` requis et absent », pas « 422 »). Le câblage vit dans
`guardrails_outils.Guardrail.before_call`, qui savait déjà répondre `allow | warn | block`.

Écarts BLOQUANTS (l'appel HTTP ne part pas) :
  outil_inconnu, param_requis, type, enum, bornes, motif
Écarts NON bloquants (annotés au résultat, l'appel part quand même) :
  param_inconnu, items — trop de faux positifs possibles pour justifier un blocage.

Tolérance de type assumée : une chaîne numérique (« 5 ») vaut un nombre, « true »/« false »
valent un booléen. Ce n'est pas du laxisme — les arguments partent en query string (GET) ou
en corps JSON vers des modèles Pydantic en mode souple, qui coercent déjà les deux. Bloquer
là-dessus serait un faux positif qui coûte le tour de LLM qu'on cherche justement à éviter.
"""

import re
from dataclasses import dataclass

# Catégories d'écart, dans l'ordre de sévérité décroissante. Sert aussi de clés de
# comptage (journal_usage) : sans cette mesure on ne saura pas si un plan explicite
# (S226) se justifie ou si la validation unitaire suffisait.
CATEGORIES = ("outil_inconnu", "param_requis", "type", "enum", "bornes", "motif",
              "param_inconnu", "items")
BLOQUANTES = frozenset({"outil_inconnu", "param_requis", "type", "enum", "bornes", "motif"})


@dataclass(frozen=True)
class Ecart:
    categorie: str
    message: str
    param: str | None = None

    @property
    def bloquant(self) -> bool:
        return self.categorie in BLOQUANTES


def _est_nombre(v, *, entier: bool) -> bool:
    """Vrai si `v` est (ou représente sans ambiguïté) un nombre du type voulu.

    `bool` est exclu explicitement : en Python `True` est un `int`, et accepter un booléen
    là où le manifeste demande un entier laisserait passer une vraie erreur du LLM."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return not entier or v.is_integer()
    if isinstance(v, str):
        try:
            f = float(v.strip())
        except ValueError:
            return False
        return not entier or f.is_integer()
    return False


def _est_booleen(v) -> bool:
    if isinstance(v, bool):
        return True
    return isinstance(v, str) and v.strip().lower() in ("true", "false", "1", "0")


def _type_ok(v, attendu: str) -> bool:
    """Conformité d'une valeur à un `type` de manifeste. Type inconnu = on ne juge pas."""
    if attendu == "string":
        return isinstance(v, str)
    if attendu == "integer":
        return _est_nombre(v, entier=True)
    if attendu == "number":
        return _est_nombre(v, entier=False)
    if attendu == "boolean":
        return _est_booleen(v)
    if attendu == "array":
        return isinstance(v, (list, tuple))
    if attendu == "object":
        return isinstance(v, dict)
    return True


def _nombre(v) -> float | None:
    try:
        return float(v.strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None


def _valider_param(nom_p: str, valeur, regle: dict) -> list[Ecart]:
    """Écarts d'UN paramètre présent. `regle` = le sous-schéma du manifeste."""
    out: list[Ecart] = []
    attendu = regle.get("type")
    if attendu and not _type_ok(valeur, attendu):
        return [Ecart("type", f"paramètre `{nom_p}` attendu de type {attendu}, reçu "
                              f"{type(valeur).__name__} ({valeur!r})", nom_p)]

    choix = regle.get("enum")
    if choix and valeur not in choix:
        out.append(Ecart("enum", f"paramètre `{nom_p}` = {valeur!r} hors des valeurs "
                                 f"admises : {', '.join(map(str, choix))}", nom_p))

    if "minimum" in regle or "maximum" in regle:
        n = _nombre(valeur)
        if n is not None:
            mini, maxi = regle.get("minimum"), regle.get("maximum")
            if mini is not None and n < mini:
                out.append(Ecart("bornes", f"paramètre `{nom_p}` = {valeur} < minimum {mini}",
                                 nom_p))
            if maxi is not None and n > maxi:
                out.append(Ecart("bornes", f"paramètre `{nom_p}` = {valeur} > maximum {maxi}",
                                 nom_p))

    motif = regle.get("pattern")
    if motif and isinstance(valeur, str):
        try:
            if not re.search(motif, valeur):
                out.append(Ecart("motif", f"paramètre `{nom_p}` = {valeur!r} ne respecte pas "
                                          f"le format attendu ({motif})", nom_p))
        except re.error:  # motif mal écrit dans un manifeste : on ne bloque pas là-dessus
            pass

    # Contrôle SUPERFICIEL des éléments d'un tableau (non bloquant : `items` peut décrire
    # des objets imbriqués qu'on ne prétend pas valider en profondeur ici).
    items = regle.get("items") or {}
    if items.get("type") and isinstance(valeur, (list, tuple)):
        mauvais = [e for e in valeur if not _type_ok(e, items["type"])]
        if mauvais:
            out.append(Ecart("items", f"paramètre `{nom_p}` : {len(mauvais)} élément(s) ne "
                                      f"sont pas de type {items['type']}", nom_p))
    return out


def valider_schema(args: dict, schema: dict) -> list[Ecart]:
    """Écarts entre `args` et un schéma function-calling (`{properties, required}`)."""
    props = (schema or {}).get("properties") or {}
    requis = (schema or {}).get("required") or []
    args = args or {}

    out: list[Ecart] = []
    for nom_p in requis:
        if args.get(nom_p) is None:
            out.append(Ecart("param_requis", f"paramètre `{nom_p}` requis et absent", nom_p))

    for nom_p, valeur in args.items():
        regle = props.get(nom_p)
        if regle is None:
            out.append(Ecart("param_inconnu", f"paramètre `{nom_p}` inconnu de cet outil",
                             nom_p))
            continue
        if valeur is None:  # omission explicite : déjà couverte par `param_requis`
            continue
        out.extend(_valider_param(nom_p, valeur, regle))
    return out


# Comptage global, en mémoire vive, du process du Cœur : {categorie: n} et
# {outil: {categorie: n}}. Alimenté par `valider()` — donc par les appels RÉELS, jamais
# par les tests qui passent un schéma à la main. C'est la mesure qui doit trancher S226 :
# si le LLM se trompe surtout d'ARGUMENTS, la validation unitaire suffit ; s'il se trompe
# d'ENCHAÎNEMENT, il faudra un plan explicite. Exposé par `/systeme/validation`.
_COMPTEURS: dict[str, int] = {}
_COMPTEURS_OUTIL: dict[str, dict[str, int]] = {}


def compteurs() -> dict:
    """Écarts observés depuis le démarrage : total par catégorie + détail par outil."""
    return {
        "par_categorie": dict(_COMPTEURS),
        "par_outil": {k: dict(v) for k, v in _COMPTEURS_OUTIL.items()},
        "total": sum(_COMPTEURS.values()),
    }


def reinitialiser_compteurs() -> None:
    _COMPTEURS.clear()
    _COMPTEURS_OUTIL.clear()


def valider(nom: str, args: dict, registre) -> list[Ecart]:
    """Écarts entre `args` et le manifeste de la capacité `nom`. Liste vide = conforme.

    Import LOCAL d'`outils` : ce module doit rester importable seul (il est purement
    fonctionnel), et `outils` tire tout le graphe des dispatchers de domaine."""
    import outils

    schema = outils.schema_arguments(nom, registre)
    if schema is None:
        ecarts = [Ecart("outil_inconnu", f"outil `{nom}` inconnu du catalogue")]
    else:
        ecarts = valider_schema(args, schema)
    for e in ecarts:
        _COMPTEURS[e.categorie] = _COMPTEURS.get(e.categorie, 0) + 1
        par_outil = _COMPTEURS_OUTIL.setdefault(nom, {})
        par_outil[e.categorie] = par_outil.get(e.categorie, 0) + 1
    return ecarts


def resume(ecarts: list[Ecart]) -> str:
    """Message unique et actionnable pour le LLM (une ligne par écart)."""
    return " ; ".join(e.message for e in ecarts)
