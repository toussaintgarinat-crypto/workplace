"""Outils du domaine « forge » (dispatch, extrait de outils.py — S115).

Forge : RAG, factures, CRM, paiements, relances, agents.
"""
from outils_communs import _confirmation, _forge_capacites, _forge_appel


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "forge_capacites":
        return await _forge_capacites(client, registre)

    if nom == "forge_rag_chercher":
        q = (args.get("q") or "").strip()
        if not q:
            return "Précise ce que tu veux chercher dans Forge."
        return await _forge_appel(client, registre, "GET", "/rag/chercher",
                                  params={"q": q}, timeout=30)

    if nom == "forge_factures_lister":
        params = {k: args[k] for k in ("type", "statut") if args.get(k)}
        return await _forge_appel(client, registre, "GET", "/facturation",
                                  params=params, timeout=30)

    if nom == "forge_crm_lister":
        params = {"statut": args["statut"]} if args.get("statut") else {}
        return await _forge_appel(client, registre, "GET", "/crm",
                                  params=params, timeout=30)

    if nom == "forge_paiement_etat":
        return await _forge_appel(client, registre, "GET", "/paiement/etat", timeout=15)

    if nom == "forge_relances_apercu":
        return await _forge_appel(client, registre, "GET", "/relances/apercu", timeout=30)

    # — ACTION —

    if nom == "forge_rag_ingerer":
        nom_doc = (args.get("nom") or "document").strip()
        if not args.get("confirme"):
            return _confirmation("ingérer dans le RAG de Forge", nom_doc)
        return await _forge_appel(client, registre, "POST", "/rag/ingerer",
                                  charge={"nom": nom_doc, "contenu": args.get("contenu", "")},
                                  timeout=60)

    if nom == "forge_lancer_agent":
        objectif = (args.get("objectif") or "").strip()
        if not args.get("confirme"):
            return _confirmation("lancer un agent Forge", objectif[:60] or "tâche")
        charge = {"objectif": objectif}
        if args.get("contexte"):
            charge["contexte"] = args["contexte"]
        return await _forge_appel(client, registre, "POST", "/agent/lancer",
                                  charge=charge, timeout=185)

    if nom == "forge_facture_creer":
        client_nom = (args.get("client") or "").strip()
        type_ = args.get("type") or "facture"
        if not args.get("confirme"):
            libelle = "devis" if type_ == "devis" else "facture"
            return _confirmation(f"créer un {libelle} Forge", client_nom or "client")
        charge = {k: args[k] for k in
                  ("client", "lignes", "type", "email", "tva_taux", "notes", "echeance")
                  if args.get(k) is not None}
        return await _forge_appel(client, registre, "POST", "/facturation",
                                  charge=charge, timeout=30)

    if nom == "forge_facture_statut":
        fid, statut = args.get("id", ""), args.get("statut", "")
        if not args.get("confirme"):
            return _confirmation(f"passer le document au statut « {statut} »", fid)
        return await _forge_appel(client, registre, "POST", f"/facturation/{fid}/statut",
                                  charge={"statut": statut}, timeout=30)

    if nom == "forge_facture_transformer":
        fid = args.get("id", "")
        if not args.get("confirme"):
            return _confirmation("transformer le devis en facture", fid)
        return await _forge_appel(client, registre, "POST",
                                  f"/facturation/{fid}/transformer", timeout=30)

    if nom == "forge_crm_creer":
        cible = (args.get("nom") or "prospect").strip()
        if not args.get("confirme"):
            return _confirmation("ajouter un prospect au CRM Forge", cible)
        charge = {k: args[k] for k in
                  ("nom", "entreprise", "email", "telephone", "statut", "valeur", "notes")
                  if args.get(k) is not None}
        return await _forge_appel(client, registre, "POST", "/crm",
                                  charge=charge, timeout=30)

    if nom == "forge_crm_modifier":
        lid = args.get("id", "")
        if not args.get("confirme"):
            cible = f"prospect {lid}" + (f" → {args['statut']}" if args.get("statut") else "")
            return _confirmation("mettre à jour le prospect", cible)
        champs = {k: args[k] for k in
                  ("statut", "valeur", "nom", "entreprise", "email", "telephone", "notes")
                  if args.get(k) is not None}
        return await _forge_appel(client, registre, "POST", f"/crm/{lid}",
                                  charge=champs, timeout=30)

    if nom == "forge_paiement_lien":
        plan = (args.get("plan") or "").strip()
        if not args.get("confirme"):
            return _confirmation("créer un lien de paiement Stripe", f"plan {plan}")
        return await _forge_appel(client, registre, "POST", "/paiement/lien",
                                  charge={"plan": plan}, timeout=30)

    if nom == "forge_relances_envoyer":
        if not args.get("confirme"):
            return _confirmation("envoyer les relances d'impayés dues", "factures J+7/15/30")
        return await _forge_appel(client, registre, "POST", "/relances/executer", timeout=60)

    if nom == "forge_facture_envoyer":
        fid = args.get("id", "")
        if not args.get("confirme"):
            return _confirmation("envoyer la facture au client par email", fid)
        return await _forge_appel(client, registre, "POST", f"/facturation/{fid}/envoyer",
                                  timeout=30)

    # — STUDIO (audio-séries) —
    return None
