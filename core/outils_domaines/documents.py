"""Outils du domaine « documents » (dispatch, extrait de outils.py — S115).

documents & données (Ingestion/Données) : lecture et écriture.
S134 : memoire_rappeler/memoire_retenir migrés vers briques/memoire/manifest.json.
"""
import json
import contexte_tenant
from outils_communs import _confirmation, _base, _entetes_brique


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "chercher_documents":
        params = {k: args[k] for k in ("categorie", "projet", "entreprise_id")
                  if args.get(k)}
        params["limite"] = 200
        r = await client.get(f"{_base(registre, 'ingestion')}/documents", params=params,
                             headers=_entetes_brique("ingestion"))
        docs = r.json().get("documents", []) if r.status_code < 400 else []
        q = (args.get("q") or "").lower()
        if q:
            docs = [d for d in docs if q in json.dumps(d, ensure_ascii=False).lower()]
        apercu = [{"id": d.get("id"), "nom": d.get("nom"), "type": d.get("type_mime"),
                   "classement": d.get("classement")} for d in docs]
        return json.dumps({"documents": apercu, "total": len(apercu)}, ensure_ascii=False)

    if nom == "lister_dossiers":
        r = await client.get(f"{_base(registre, 'ingestion')}/dossiers",
                             headers=_entetes_brique("ingestion"))
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else "Brique ingestion injoignable."

    if nom == "lire_document":
        r = await client.get(f"{_base(registre, 'ingestion')}/documents/{args.get('doc_id','')}",
                             headers=_entetes_brique("ingestion"))
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

    if nom == "ingerer_document":
        url = args.get("url", "")
        if not args.get("confirme"):
            return _confirmation("ingérer le document", url)
        r = await client.post(f"{_base(registre, 'ingestion')}/ingerer/url", json={"url": url},
                              headers=_entetes_brique("ingestion"))
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec ingestion : {r.text}"

    if nom == "classer_document":
        doc_id = args.get("doc_id", "")
        if not args.get("confirme"):
            return _confirmation("classer le document", doc_id)
        classement = {k: args[k] for k in
                      ("categorie", "tags", "entreprise_id", "projet", "resume")
                      if args.get(k) is not None}
        r = await client.patch(
            f"{_base(registre, 'ingestion')}/documents/{doc_id}/classement", json=classement,
            headers=_entetes_brique("ingestion"))
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec classement : {r.text}"

    if nom == "creer_enregistrement":
        app_id, entite = args.get("app_id", ""), args.get("entite", "")
        if not args.get("confirme"):
            return _confirmation("créer un enregistrement", f"{entite} (app {app_id})")
        r = await client.post(
            f"{_base(registre, 'donnees')}/apps/{app_id}/entites/{entite}/enregistrements",
            json=args.get("donnees") or {}, headers=contexte_tenant.entetes_donnees())
        return json.dumps(r.json(), ensure_ascii=False) if r.status_code < 400 else f"Échec : {r.text}"

    return None
