"""Outils du domaine « documents » (dispatch, extrait de outils.py — S115).

documents & données (ETL/Données/Mémoire) : lecture et écriture.
"""
import json
import contexte_tenant
from outils_communs import _confirmation, _base, _espace_memoire


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "chercher_documents":
        params = {k: args[k] for k in ("categorie", "projet", "entreprise_id")
                  if args.get(k)}
        params["limite"] = 200
        r = await client.get(f"{_base(registre, 'etl')}/documents", params=params)
        docs = r.json().get("documents", []) if r.status_code < 400 else []
        q = (args.get("q") or "").lower()
        if q:
            docs = [d for d in docs if q in json.dumps(d, ensure_ascii=False).lower()]
        apercu = [{"id": d.get("id"), "nom": d.get("nom"), "type": d.get("type_mime"),
                   "classement": d.get("classement")} for d in docs]
        return json.dumps({"documents": apercu, "total": len(apercu)}, ensure_ascii=False)

    if nom == "lister_dossiers":
        r = await client.get(f"{_base(registre, 'etl')}/dossiers")
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "ETL injoignable."

    if nom == "lire_document":
        r = await client.get(f"{_base(registre, 'etl')}/documents/{args.get('doc_id','')}")
        if r.status_code >= 400:
            return "Document introuvable."
        d = r.json()
        return json.dumps({"id": d.get("id"), "nom": d.get("nom"),
                           "texte": (d.get("texte_extrait") or "")[:2000]}, ensure_ascii=False)

    if nom == "lister_apps":
        r = await client.get(f"{_base(registre, 'generateur')}/apps")
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Générateur injoignable."

    if nom == "consulter_donnees":
        r = await client.get(f"{_base(registre, 'donnees')}/apps/{args.get('app_id','')}/resume")
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Données injoignables."

    if nom == "memoire_rappeler":
        params = {"q": args.get("requete", "")}
        esp = _espace_memoire(args.get("espace"))
        if esp:
            params["espace"] = esp
        r = await client.get(f"{_base(registre, 'memoire')}/rappeler", params=params)
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Mémoire injoignable."

    if nom == "ingerer_document":
        url = args.get("url", "")
        if not args.get("confirme"):
            return _confirmation("ingérer le document", url)
        r = await client.post(f"{_base(registre, 'etl')}/ingerer/url", json={"url": url})
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec ingestion : {r.text}"

    if nom == "classer_document":
        doc_id = args.get("doc_id", "")
        if not args.get("confirme"):
            return _confirmation("classer le document", doc_id)
        classement = {k: args[k] for k in
                      ("categorie", "tags", "entreprise_id", "projet", "resume")
                      if args.get(k) is not None}
        r = await client.patch(
            f"{_base(registre, 'etl')}/documents/{doc_id}/classement", json=classement)
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec classement : {r.text}"

    if nom == "creer_enregistrement":
        app_id, entite = args.get("app_id", ""), args.get("entite", "")
        if not args.get("confirme"):
            return _confirmation("créer un enregistrement", f"{entite} (app {app_id})")
        r = await client.post(
            f"{_base(registre, 'donnees')}/apps/{app_id}/entites/{entite}/enregistrements",
            json=args.get("donnees") or {}, headers=contexte_tenant.entetes_donnees())
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec : {r.text}"

    if nom == "memoire_retenir":
        if not args.get("confirme"):
            return _confirmation("mémoriser", (args.get("titre") or args.get("contenu", ""))[:60])
        corps_mem = {"contenu": args.get("contenu", ""), "titre": args.get("titre")}
        esp = _espace_memoire(args.get("espace"))
        if esp:
            corps_mem["espace"] = esp
        r = await client.post(f"{_base(registre, 'memoire')}/retenir", json=corps_mem)
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec mémorisation : {r.text}"
    return None
