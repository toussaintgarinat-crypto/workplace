"""Reprise après approbation (S245b) : le Cœur exécute lui-même l'action approuvée.

Avant S245b, approuver ne faisait que passer la demande à `approuvee` : il fallait que le LLM
rappelle l'outil dans les 5 min, et le co-agent / les incidents n'avaient aucune reprise.
Ici, à l'approbation (bouton, ou code à 6 chiffres), on rejoue `outils.executer` dans le contexte
du DEMANDEUR (utilisateur, organisation, origine) avec les arguments exacts persistés.

## Garanti
- Une seule exécution : la garde consomme CETTE approbation par un UPDATE conditionnel
  (`approbations.consommer_id`) ; deux reprises concurrentes (ou un rappel du LLM) n'exécutent
  qu'une fois.
- Jamais de nouvelle demande : en mode reprise, `exiger` ne crée rien.
- Au plus une exécution : `executee` est posé AVANT l'exécution (un crash ne rejoue pas).

## NON garanti
- Le JWT de l'utilisateur n'est pas persisté : une capacité qui l'exige échoue (état `echec`).
- Le résultat n'est pas réinjecté dans le fil de conversation (visible dans le message Telegram
  édité et dans `approbations.resultat`).
- Une exception AVANT la consommation (ex. base verrouillée) laisse la demande `approuvee` :
  elle est journalisée, et l'horloge (`/approbations/relancer` → `a_reprendre`) la reprendra
  jusqu'à son expiration."""
import asyncio
import logging

import approbations
import contexte_tenant
import outils

log = logging.getLogger(__name__)

_TACHES: set[asyncio.Task] = set()          # références fortes (sinon le GC peut tuer la tâche)


async def reprendre(registre, id_: str) -> str:
    """Exécute l'approbation `id_` si elle est `approuvee`. Ne lève jamais.

    Renvoie `executee` | `ignoree` | `sans_args` | `non_consommee` (la garde a refusé sans
    lever : rien n'a été exécuté, demande abandonnée) | `echec` (exception).
    Une capacité devenue non sensible (ou de niveau différent) n'est PAS exécutée : abandon."""
    jetons = None
    try:
        demande = approbations.lire(id_)
        if not demande or demande["statut"] != "approuvee":
            return "ignoree"
        niveau = outils.est_sensible(demande["capacite"], registre)
        if not niveau or niveau != demande.get("sensibilite"):
            # Sans garde, `outils.executer` n'appellerait pas `exiger` : la demande ne serait
            # jamais consommée et l'action pourrait être rejouée sans contrôle. On n'exécute pas.
            log.warning("approbation %s : capacité plus sensible/introuvable, abandon", id_[:8])
            approbations.abandonner(id_, "capacité plus sensible/introuvable")
            return "ignoree"
        args = approbations.args_de(id_)
        if args is None:
            log.warning("approbation %s : reprise impossible (arguments absents)", id_[:8])
            return "sans_args"
        jetons = contexte_tenant.definir_contexte(utilisateur=demande["utilisateur"],
                                                  org_id=demande.get("org_id"))
        with approbations.avec_origine(demande["origine"]), approbations.avec_reprise(id_):
            await outils.executer(demande["capacite"], args, registre)
        if approbations.lire(id_)["statut"] == "approuvee":
            log.warning("approbation %s : reprise sans effet (garde refusée, non consommée), "
                        "abandon", id_[:8])
            approbations.abandonner(id_, "garde refusée à la reprise (non consommée)")
            return "non_consommee"
        return "executee"
    except Exception as exc:  # noqa: BLE001 — jamais remonter dans une tâche de fond
        log.warning("approbation %s : reprise en échec (%s)", id_[:8], type(exc).__name__)
        try:
            # `executee -> echec` seulement ; no-op si la demande n'a pas été consommée.
            approbations.conclure(id_, False, f"reprise : {type(exc).__name__}")
            if approbations.lire(id_)["statut"] == "approuvee":
                log.warning("approbation %s : exception avant consommation, demande non "
                            "consommée (restera reprenable par l'horloge)", id_[:8])
        except Exception as exc2:  # noqa: BLE001
            log.warning("approbation %s : état final illisible (%s)", id_[:8],
                        type(exc2).__name__)
        return "echec"
    finally:
        if jetons is not None:
            contexte_tenant.reinitialiser(jetons)


def lancer(registre, id_: str) -> None:
    """Planifie `reprendre` en tâche de fond : la route de décision répond sans attendre.
    À appeler depuis une coroutine (boucle active)."""
    tache = asyncio.get_running_loop().create_task(reprendre(registre, id_))
    _TACHES.add(tache)
    tache.add_done_callback(_TACHES.discard)
