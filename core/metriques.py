"""Métriques d'exploitation du Cœur (S225).

## Pourquoi

On avait de l'**état instantané** — `/sante` par brique, `pouls`, `proprioception`, le
journal JSONL des appels LLM — et aucune **série temporelle**. À 39 briques, ce qui se
dégrade lentement passe inaperçu : les modèles gratuits de la Gateway sont restés figés
**51 jours** sans que personne le voie, et une thématique de veille est morte à 100 %
(5 sources sur 5) avant qu'on s'en aperçoive. Une métrique de fraîcheur aurait crié le
deuxième jour.

## Ce qu'on expose, et ce qu'on n'expose pas

Une dizaine de métriques **métier**, pas 464 techniques : chacune répond à une question
qu'on s'est effectivement posée trop tard. L'inflation de métriques est un piège en soi —
un tableau de bord que personne ne lit ne vaut pas mieux que pas de tableau de bord.

⚠ **Le scrape ne fait AUCUN appel réseau.** Tout vient du disque local (SQLite de
l'horloge, journal JSONL d'usage) ou de la mémoire du processus. Un `/metrics` qui sonde
39 briques deviendrait lent, puis timeout, puis serait la cause de la panne qu'il devait
signaler. La santé live reste le domaine de `/briques/{nom}/sante` et du pouls.

Corollaire honnête : les compteurs en mémoire (`workplace_outil_*`,
`workplace_validation_ecarts_total`) repartent de zéro à chaque redémarrage du Cœur.
C'est la convention Prometheus pour un `counter` (`rate()` sait le gérer) ;
`workplace_demarrage_timestamp_secondes` permet de dater la remise à zéro.
"""

import time
from datetime import datetime, timezone

import horloge
import journal_usage
import outils
import validation_args
from shared.metriques import Registre

DEMARRAGE = time.time()


def _age_secondes(iso: str | None) -> float | None:
    """Secondes écoulées depuis un horodatage ISO. None si absent/illisible."""
    if not iso:
        return None
    try:
        quand = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - quand).total_seconds())


def _taches(registre, r: Registre) -> None:
    """Fraîcheur des tâches planifiées — LA métrique du sprint.

    `workplace_tache_age_secondes` est le signal central : « depuis combien de temps cette
    tâche n'a-t-elle pas tourné ? ». Comparé à sa cadence déclarée, il dit tout seul si
    une source de veille s'est tue ou si une synchro est morte."""
    try:
        etats = horloge.lister_etat(registre)
    except Exception:  # noqa: BLE001 — l'observabilité ne casse jamais le Cœur
        return
    for t in etats:
        etiq = {"brique": t.get("brique"), "tache": t.get("nom")}
        age = _age_secondes(t.get("derniere_execution"))
        # Jamais exécutée : on n'invente PAS un âge de 0 (qui se lirait « toute fraîche »).
        # La métrique est simplement absente, et `workplace_tache_jamais_executee` le dit.
        if age is not None:
            r.jauge("workplace_tache_age_secondes", age, etiq,
                    aide="Secondes depuis la dernière exécution d'une tâche planifiée.")
        r.jauge("workplace_tache_jamais_executee", 0 if age is not None else 1, etiq,
                aide="1 si la tâche déclarée n'a jamais tourné depuis l'installation.")
        # Arrondi : `cadence_heures` est souvent fractionnaire (0,8333 h pour 50 min) et
        # la conversion sortait des `2.9987999999999997` illisibles dans les alertes.
        r.jauge("workplace_tache_cadence_secondes",
                round(float(t.get("cadence_heures") or 0) * 3600, 3), etiq,
                aide="Cadence déclarée dans le manifeste, en secondes.")
        r.jauge("workplace_tache_dernier_succes",
                1 if t.get("dernier_statut") == "ok" else 0, etiq,
                aide="1 si la dernière exécution a réussi, 0 sinon.")
        r.compteur("workplace_tache_executions_total",
                   int(t.get("nb_executions") or 0), etiq,
                   aide="Nombre d'exécutions d'une tâche planifiée.")


def _llm(r: Registre) -> None:
    """Coût LLM et état du budget — les deux seules choses qui coûtent de l'argent réel."""
    try:
        resume = journal_usage.resume()
    except Exception:  # noqa: BLE001
        return
    for periode in ("jour", "mois"):
        agg = resume.get(periode) or {}
        r.jauge("workplace_llm_cout_usd", agg.get("cout_usd", 0), {"periode": periode},
                aide="Dépense LLM cumulée sur la période courante, en USD.")
        r.jauge("workplace_llm_appels", agg.get("appels", 0), {"periode": periode},
                aide="Nombre d'appels LLM sur la période courante.")
        r.jauge("workplace_llm_cache_hits", agg.get("cache_hits", 0), {"periode": periode},
                aide="Appels servis par le cache sémantique (S138).")
        budget = (resume.get("budget") or {}).get(periode) or {}
        plafond = budget.get("budget_usd") or 0
        # Ratio seulement quand un plafond existe : 0 sur budget illimité se lirait
        # « on ne dépense rien », ce qui est faux.
        if plafond > 0:
            r.jauge("workplace_llm_budget_ratio",
                    (budget.get("depense_usd") or 0) / plafond, {"periode": periode},
                    aide="Dépense / plafond. ≥0,95 = les appels payants sont bloqués.")


def _outils(registre, r: Registre) -> None:
    """Usage réel des capacités : taux d'échec, et surtout celles que PERSONNE n'appelle.

    S210 avait découvert 4 capacités MORTES (déclarées, routées, jamais appelables). Sans
    compteur d'usage on ne peut pas répondre à « à quoi sert vraiment ce catalogue ? »."""
    appels, echecs = outils.compteurs_appels()
    for nom, n in appels.items():
        etiq = {"outil": nom, "brique": outils.brique_de(nom, registre)}
        r.compteur("workplace_outil_appels_total", n, etiq,
                   aide="Appels d'outil depuis le démarrage du Cœur.")
        r.compteur("workplace_outil_echecs_total", echecs.get(nom, 0), etiq,
                   aide="Appels d'outil terminés en erreur depuis le démarrage.")
    try:
        import catalogue
        capacites = catalogue.collecter_capacites(registre)
    except Exception:  # noqa: BLE001
        capacites = []
    r.jauge("workplace_capacites_declarees", len(capacites),
            aide="Capacités déclarées par les manifestes des briques.")
    jamais = [c for c in capacites if c["nom"] not in appels]
    r.jauge("workplace_capacites_jamais_appelees", len(jamais),
            aide="Capacités jamais appelées depuis le démarrage du Cœur.")


def _validation(r: Registre) -> None:
    """Écarts d'arguments (S221) : la mesure qui doit trancher S226."""
    try:
        compteurs = validation_args.compteurs()
    except Exception:  # noqa: BLE001
        return
    for categorie, n in (compteurs.get("par_categorie") or {}).items():
        r.compteur("workplace_validation_ecarts_total", n, {"categorie": categorie},
                   aide="Arguments d'outil refusés ou signalés, par catégorie d'écart.")


def rendu(registre) -> str:
    """Texte d'exposition Prometheus complet. Ne lève jamais : une sonde qui plante en
    scrutant est pire qu'une sonde absente."""
    r = Registre()
    r.jauge("workplace_demarrage_timestamp_secondes", DEMARRAGE,
            aide="Horodatage Unix du démarrage du Cœur (date la remise à zéro "
                 "des compteurs en mémoire).")
    try:
        r.jauge("workplace_briques_declarees", len(getattr(registre, "briques", {}) or {}),
                aide="Briques présentes dans le registre.")
    except Exception:  # noqa: BLE001
        pass
    for collecte in (lambda: _taches(registre, r), lambda: _llm(r),
                     lambda: _outils(registre, r), lambda: _validation(r)):
        try:
            collecte()
        except Exception:  # noqa: BLE001 — une famille en panne n'emporte pas les autres
            continue
    return r.rendu()
