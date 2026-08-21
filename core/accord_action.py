"""L'accord humain sur les actions, tenu par le Cœur (S222).

## Le trou que ce module ferme

Avant S222, le gate d'action était **purement déclaratif**. Une capacité `action: true`
appelée sans `confirme` recevait `_confirmation()` (`outils_communs.py`) : un TEXTE qui
demande poliment au LLM d'attendre l'accord de l'utilisateur. Côté Cœur,
`assistant.py` se contentait de poser un drapeau sur l'événement SSE. Rien n'empêchait
structurellement le modèle de rappeler le même outil avec `confirme=true` **dans le même
tour**, sans que l'humain ait jamais vu la question. Le seul rempart était son obéissance au
prompt — sur 133 capacités marquées `action: true`, dont les envois de mail de prospection.

## Ce que ce module garantit — et ce qu'il ne garantit pas

**Garanti, structurellement** : une action ne s'exécute que si un message UTILISATEUR est
arrivé *après* que la demande de confirmation a été émise. Le LLM ne peut plus fabriquer
l'aller-retour tout seul : il faut un vrai tour de parole humain entre les deux.

**Garanti aussi** : l'accord porte sur des arguments PRÉCIS (empreinte). Un accord obtenu pour
« envoyer à Alice » ne peut pas être dépensé sur « envoyer à Bob », ni recyclé sur 50
destinataires — c'est le pendant du « seuil 1 sur les mutations en masse » de LIA, obtenu sans
notion de plan : N mutations exigent N accords, donc N tours de parole.

**NON garanti** : que l'humain ait dit « oui » plutôt qu'autre chose. Interpréter la réponse
reste le travail du LLM — le Cœur ne fait pas d'analyse sémantique. Le Cœur tranche seulement
dans le sens conservateur : si le message ressemble à un refus explicite, l'accord est révoqué
quoi qu'en dise le modèle. Un refus détecté à tort coûte une redemande ; un accord accordé à
tort exigeait déjà un tour humain. Les deux erreurs penchent du bon côté.

## Portée

En mémoire vive, par processus du Cœur. Un redémarrage perd les accords en attente : il faut
reconfirmer. C'est le sens sûr. Ce module ne couvre PAS les chemins qui n'ont pas de tour de
parole humain (co-agent autonome, Gateway MCP) — ils gardent le comportement antérieur, cf.
l'ADR.
"""

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256

# Durée de vie d'une demande en attente ET d'un accord accordé. Court volontairement :
# un accord qui traîne est un accord qu'on a oublié avoir donné.
TTL_SECONDES = int(os.getenv("ACCORD_TTL_SECONDES", "600"))

# Au-delà de N lectures de la MÊME capacité dans un tour, on annote (sans bloquer).
# Pendant du seuil « lecture en lot » de LIA : consultatif, parce que bloquer une lecture
# légitime coûterait plus cher que le risque couvert.
SEUIL_LECTURE_LOT = int(os.getenv("ACCORD_SEUIL_LECTURE_LOT", "8"))

# Refus explicites. Liste volontairement COURTE et ancrée sur des frontières de mots : un
# faux positif ne coûte qu'une redemande, mais un « pas » attrapé au vol dans « oui mais pas
# à Bob » transformerait un accord nuancé en refus incompréhensible.
_REFUS = re.compile(
    r"\b(non|nope|annule|annuler|annulation|stop|arrete|arreter|abandonne|"
    r"laisse tomber|surtout pas|n'?envoie pas|ne fais pas|pas maintenant)\b")


def _sans_accents(texte: str) -> str:
    """Casefold + retrait des accents : « ANNULÉ », « annule » et « Annulé » sont un
    seul et même refus. (Le piège de casse a déjà coûté un correctif sur l'opt-out mail.)"""
    plie = unicodedata.normalize("NFD", texte or "").casefold()
    return "".join(c for c in plie if unicodedata.category(c) != "Mn")


def est_refus(message: str) -> bool:
    return bool(_REFUS.search(_sans_accents(message)))


def cle(fil: str | None, utilisateur: str | None) -> str:
    """Clé du registre d'accords : le fil de conversation ET la personne.

    Le fil seul ne suffit PAS. `journal_conversations.fil()` vaut « web:dashboard » pour
    toute la surface web — l'interlocuteur y est la surface, pas la personne. Depuis
    l'identité multi-utilisateur du Cœur (S182/S217), deux personnes connectées
    partageraient donc le même registre : le « oui » de l'une validerait l'action en
    attente de l'autre. La personne inconnue (`None`) reste cloisonnée sous son propre
    seau, jamais fondue avec les sessions identifiées."""
    return f"{fil or 'sans-fil'}\x00{utilisateur or '-'}"


def empreinte(nom: str, args: dict) -> str:
    """Identité stable d'une action : sa capacité + ses arguments effectifs.

    `confirme` est retiré (c'est le drapeau, pas la cible) et les valeurs nulles aussi :
    `{"a": 1}` et `{"a": 1, "b": None}` désignent la même action, et `_appel_dynamique`
    filtre déjà les `None` avant l'envoi."""
    utiles = {k: v for k, v in (args or {}).items() if k != "confirme" and v is not None}
    brut = nom + "\x00" + "\x00".join(f"{k}={utiles[k]!r}" for k in sorted(utiles))
    return sha256(brut.encode()).hexdigest()[:16]


@dataclass
class _Demande:
    nom: str
    empreinte: str
    emise_a: float
    accordee: bool = False


@dataclass
class Registre:
    """Accords d'une instance de Cœur, indexés par fil de conversation."""

    _demandes: dict[str, list[_Demande]] = field(default_factory=dict)
    _lectures: dict[str, dict[str, int]] = field(default_factory=dict)

    # ── Côté LLM : demander, puis consommer ──────────────────────────────────

    def demander(self, fil: str, nom: str, args: dict) -> None:
        """Enregistre qu'une confirmation a été DEMANDÉE pour cette action précise.

        Appelé quand le LLM appelle une action sans `confirme`. C'est le seul moyen de
        rendre un futur `confirme=true` recevable."""
        emp = empreinte(nom, args)
        self._purger(fil)
        en_cours = self._demandes.setdefault(fil, [])
        if any(d.empreinte == emp and not d.accordee for d in en_cours):
            return  # déjà en attente : ne pas empiler
        en_cours.append(_Demande(nom=nom, empreinte=emp, emise_a=time.time()))

    def consommer(self, fil: str, nom: str, args: dict) -> tuple[bool, str | None]:
        """L'action peut-elle s'exécuter ? Retourne (autorisée, message de refus).

        Un accord est à USAGE UNIQUE : consommé ici, il ne peut pas resservir au tour
        suivant sur la même cible sans un nouvel aller-retour humain."""
        self._purger(fil)
        emp = empreinte(nom, args)
        for d in self._demandes.get(fil, []):
            if d.empreinte == emp and d.accordee:
                self._demandes[fil].remove(d)
                return True, None
        if any(d.empreinte == emp for d in self._demandes.get(fil, [])):
            return False, (
                f"Action `{nom}` NON exécutée : la confirmation a été demandée mais "
                "l'utilisateur n'a pas encore répondu. Attends sa réponse — n'appelle pas "
                "`confirme=true` de ta propre initiative.")
        return False, (
            f"Action `{nom}` NON exécutée : aucun accord de l'utilisateur n'a été "
            "enregistré pour ces arguments exacts. Appelle d'abord l'outil SANS `confirme` "
            "pour lui poser la question, et attends sa réponse.")

    # ── Côté humain : un tour de parole ──────────────────────────────────────

    def tour_utilisateur(self, fil: str, message: str) -> None:
        """Un message utilisateur est arrivé : les demandes en attente deviennent des
        accords — sauf s'il s'agit d'un refus explicite, auquel cas elles disparaissent.

        C'est ICI que se joue toute la garantie : sans passage par cette méthode, aucune
        demande ne devient jamais un accord, et donc aucun `confirme=true` ne passe.

        Un message vide N'EST PAS un tour de parole (S234, audit gate-forge) : sans ce
        garde-fou, un appel qui atteint cette méthode sans avoir extrait de VRAI message
        utilisateur accordait quand même toutes les demandes en attente. Le retour anticipé
        laisse aussi intacts les compteurs de lecture (`_lectures`) : un message vide n'est
        pas un tour, donc rien ne doit en dépendre — ni un accord, ni une remise à zéro."""
        if not (message or "").strip():
            return
        self._purger(fil)
        self._lectures.pop(fil, None)  # nouveau tour : les compteurs de lecture repartent
        en_cours = self._demandes.get(fil) or []
        if not en_cours:
            return
        if est_refus(message or ""):
            self._demandes[fil] = []
            return
        maintenant = time.time()
        for d in en_cours:
            d.accordee = True
            d.emise_a = maintenant  # le TTL court à partir de l'accord, pas de la demande

    # ── Lectures en lot : consultatif ────────────────────────────────────────

    def noter_lecture(self, fil: str, nom: str) -> str | None:
        """Compte les lectures répétées d'une même capacité dans le tour courant.
        Renvoie une note à annexer au résultat au-delà du seuil, jamais un blocage."""
        compte = self._lectures.setdefault(fil, {})
        compte[nom] = compte.get(nom, 0) + 1
        if compte[nom] == SEUIL_LECTURE_LOT:
            return (f"`{nom}` a déjà été lu {compte[nom]}× dans ce tour — si tu balayes une "
                    "collection, résume ce que tu as plutôt que de continuer.")
        return None

    # ── Interne ──────────────────────────────────────────────────────────────

    def _purger(self, fil: str) -> None:
        limite = time.time() - TTL_SECONDES
        restantes = [d for d in self._demandes.get(fil, []) if d.emise_a >= limite]
        if restantes:
            self._demandes[fil] = restantes
        else:
            self._demandes.pop(fil, None)

    def etat(self, fil: str) -> dict:
        """Inspection (dashboard, tests) : ce que le Cœur retient pour ce fil."""
        self._purger(fil)
        return {"en_attente": [d.nom for d in self._demandes.get(fil, []) if not d.accordee],
                "accordees": [d.nom for d in self._demandes.get(fil, []) if d.accordee]}


# Registre du processus. Le Cœur est mono-processus (uvicorn) : un seul registre suffit,
# et un redémarrage repart d'accords vides — le sens sûr.
REGISTRE = Registre()
