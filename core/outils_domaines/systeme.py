"""Outils du domaine « systeme » (dispatch, extrait de outils.py — S115).

registre, santé des briques, méta-outils (competence_charger, mes_capacites, co-agent).
"""
import json
import conscience
import orchestrateur
from outils_communs import _resume_liv, _etat_briques


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    import outils  # machinerie de specs (accès paresseux : casse le cycle)
    if nom == "lister_entreprises":
        liv = [_resume_liv(l) for l in orchestrateur.lister_livraisons()]
        return json.dumps({"entreprises": liv, "total": len(liv)}, ensure_ascii=False)

    if nom == "details_entreprise":
        l = orchestrateur.lire_livraison(args.get("livraison_id", ""))
        return json.dumps(l, ensure_ascii=False) if l else "Aucune entreprise avec cet identifiant."

    if nom == "etat_briques":
        return json.dumps(await _etat_briques(client, registre), ensure_ascii=False)

    if nom == outils.META_CHARGER:
        # La porte (S90) : ouvre une compétence différée. On renvoie son schéma
        # complet — la boucle de l'assistant l'ajoutera aux outils du tour suivant.
        cible = (args or {}).get("nom", "")
        cap = outils._capacites_dynamiques(registre).get(cible)
        if not cap:
            return json.dumps({"ok": False, "message": f"Compétence inconnue : {cible}."},
                              ensure_ascii=False)
        return json.dumps(
            {"ok": True, "chargee": cible,
             "outil": outils._spec_depuis_capacite(cap)["function"],
             "message": f"Compétence « {cible} » chargée — appelle-la maintenant."},
            ensure_ascii=False)

    if nom == "mes_capacites":
        # Conscience de soi (S65) : on rend l'anatomie depuis la source de vérité
        # (manifests + outils réellement actifs) — pas de confabulation.
        return json.dumps(
            conscience.anatomie(registre, outils.outils_pour(registre),
                                lambda n: outils.est_action(n, registre)),
            ensure_ascii=False)

    if nom == "graphe_rafraichir":
        import graphe_apprentissage
        import routage_outils
        specs = outils.outils_pour(registre)
        await graphe_apprentissage.charger_graphe(specs)
        await routage_outils.indexer(specs, client)
        st = graphe_apprentissage._graphe.stats()
        return json.dumps({
            "ok": True,
            "capacites_liees": st["capacites_liees"],
            "top5": st["top5"],
            "index_outils": len(routage_outils._index),
        }, ensure_ascii=False)

    if nom == "coagent_lancer":
        # Co-agent exécutif (S66) : boucle profonde autonome, bornée en tokens,
        # lecture seule. Import LOCAL — coagent importe outils, on casse le cycle.
        import coagent
        # Client dédié (le client local est à 30 s : trop court pour des appels LLM
        # profonds) ; coagent en ouvre un à 120 s s'il n'en reçoit pas.
        cr = await coagent.executer_objectif(
            args.get("objectif", ""), registre,
            budget_tokens=args.get("budget_tokens"),
            max_etapes=args.get("max_etapes"))
        return json.dumps(cr, ensure_ascii=False)
    return None
