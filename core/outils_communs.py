"""Plomberie partagée des outils (S115) : helpers HTTP sans état appelés par les
modules de dispatch par domaine (outils_domaines) et par la façade outils.py.
Aucune logique de catalogue/capacités ici (elle reste dans outils.py).
"""
import asyncio
import json
import os
import uuid
import httpx
import orchestrateur


def _confirmation(action: str, cible: str) -> str:
    return json.dumps({
        "confirmation_requise": True, "action": action, "cible": cible,
        "message": f"Action « {action} » sur « {cible} » PAS encore exécutée. "
                   "Si l'utilisateur a DÉJÀ donné son accord dans la conversation "
                   "(ex. « oui », « vas-y », « confirme »), tu DOIS rappeler MAINTENANT le "
                   "même outil avec confirme=true — n'émets AUCUN texte, ne redemande PAS "
                   "l'accord une seconde fois. Si l'accord n'a pas encore été donné, "
                   "demande-lui simplement de confirmer.",
    }, ensure_ascii=False)


def _resume_liv(l: dict) -> dict:
    return {"livraison_id": l.get("id"), "nom_entreprise": l.get("nom_entreprise"),
            "statut": l.get("statut"), "app_id": l.get("app_id"), "dossier": l.get("dossier")}


def _base(registre, nom: str) -> str:
    return orchestrateur._brique_base(registre, nom)


def _espace_memoire(espace: str | None) -> str | None:
    """Mappe l'espace logique de l'assistant → nom d'espace de la brique Mémoire.
    'solution' (défaut) → None (= espace « Workplace » côté brique) ; 'perso' → « Perso »."""
    return "Perso" if (espace or "").lower() == "perso" else None


# ── Outils DYNAMIQUES : le système nerveux découvert (S64) ────────────────────
# Les capacités déclarées dans les manifests (S63) deviennent de vrais outils du LLM,
# routés ici sans une ligne de dispatch en dur. Garde-fous : un nom déjà servi par un
# outil CÂBLÉ gagne toujours (zéro régression) ; liste blanche et kill-switch d'env
# permettent de borner ce que le LLM voit (souveraineté du « plan de contrôle »).


def _entetes_brique(brique: str) -> dict:
    """Auth optionnelle : clé de service ``{BRIQUE}_KEY`` → en-tête X-API-Key (motif muscle.py)."""
    cle = os.environ.get(f"{brique.upper()}_KEY")
    return {"X-API-Key": cle} if cle else {}


def _url_dynamique(cap: dict, args: dict) -> str:
    """URL de la capacité, avec substitution des params de chemin ``{x}`` depuis les args."""
    url = cap["url"]
    if "{" in url:
        for k, v in args.items():
            url = url.replace("{" + k + "}", str(v))
    return url


async def _appel_dynamique(client, cap: dict, args: dict) -> str:
    """Exécute une capacité découverte : gate de confirmation si action, puis appel HTTP.

    GET → query params ; autres méthodes → corps JSON. Les params consommés par le chemin
    ne sont pas renvoyés en double. Verdict honnête sur refus/injoignable."""
    args = dict(args or {})
    confirme = args.pop("confirme", None)
    if cap.get("action") and not confirme:
        return _confirmation(cap["nom"], cap["brique"])
    url = _url_dynamique(cap, args)
    charge = {k: v for k, v in args.items()
              if v is not None and ("{" + k + "}") not in cap["chemin"]}
    entetes = _entetes_brique(cap["brique"]) or None
    if cap["methode"] == "GET":
        r = await client.request("GET", url, params=charge, headers=entetes)
    else:
        r = await client.request(cap["methode"], url, json=charge, headers=entetes)
    if r.status_code >= 400:
        return json.dumps({"ok": False, "brique": cap["brique"],
                           "message": f"Brique « {cap['brique']} » a refusé ({r.status_code})."},
                          ensure_ascii=False)
    try:
        return json.dumps(r.json(), ensure_ascii=False)
    except ValueError:
        return (r.text or "")[:1000]


# ── Répartiteur ──────────────────────────────────────────────────────────────


async def _livrer(registre, args: dict) -> str:
    mode = "hebergee" if args.get("persistance", "hebergee") == "hebergee" else "autonome"
    nom = args.get("nom_entreprise") or "Entreprise"
    livraison_id = str(uuid.uuid4())
    orchestrateur.creer_livraison(livraison_id, nom, mode,
                                  bool(args.get("messagerie", False)), bool(args.get("packager", False)))
    asyncio.create_task(orchestrateur.executer_pipeline(
        registre, livraison_id, [], mode, bool(args.get("messagerie", False)), bool(args.get("packager", False))))
    return json.dumps({"lancee": True, "livraison_id": livraison_id, "nom_entreprise": nom,
                       "statut": "en_cours", "note": "Suis l'avancement avec details_entreprise."},
                      ensure_ascii=False)


async def _forge_capacites(client: httpx.AsyncClient, registre) -> str:
    """Agrège /capacites + /sante de l'adaptateur Forge (lecture seule).

    Dégrade proprement si Forge est down : message clair, jamais de stacktrace —
    l'assistant doit pouvoir dire « Forge est hors ligne » plutôt que planter.
    """
    base = _base(registre, "forge")
    try:
        rc = await client.get(f"{base}/capacites", timeout=6)
    except httpx.HTTPError:
        return json.dumps({
            "en_ligne": False,
            "message": "La brique Forge est injoignable (hors ligne ou en cours de démarrage).",
        }, ensure_ascii=False)
    if rc.status_code >= 400:
        return json.dumps({
            "en_ligne": False,
            "message": f"Forge a répondu en erreur (HTTP {rc.status_code}).",
        }, ensure_ascii=False)

    capas = rc.json()
    # Santé agrégée (tolérante : on garde les capacités même si /sante échoue).
    sante = {"statut": "inconnu"}
    try:
        rs = await client.get(f"{base}/sante", timeout=6)
        sante = rs.json() if rs.status_code < 400 else {"statut": "degrade"}
    except httpx.HTTPError:
        sante = {"statut": "injoignable"}

    return json.dumps({
        "en_ligne": bool(capas.get("core_en_ligne")),
        "sante": sante.get("statut"),
        "capacites": capas.get("capacites", []),
        "note": capas.get("note"),
    }, ensure_ascii=False)


async def _forge_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                       charge: dict | None = None, params: dict | None = None,
                       timeout: float = 30) -> str:
    """Appelle une route fonctionnelle de l'adaptateur Forge (S17) et renvoie une

    chaîne pour le LLM. Dégrade proprement (jamais de stacktrace) : Forge hors ligne,
    auth de service absente ou core en erreur → message clair que l'assistant peut
    relayer. L'auth machine-à-machine est gérée *dans* l'adaptateur Forge.
    """
    base = _base(registre, "forge")
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  timeout=timeout)
    except httpx.HTTPError:
        return json.dumps({"ok": False,
                           "message": "La brique Forge est injoignable (hors ligne ou en démarrage)."},
                          ensure_ascii=False)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = r.text[:200]
        return json.dumps({"ok": False,
                           "message": f"Forge n'a pas pu traiter la demande (HTTP {r.status_code}) : {detail}"},
                          ensure_ascii=False)
    return json.dumps(r.json(), ensure_ascii=False)


async def _studio_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                        charge: dict | None = None, params: dict | None = None,
                        timeout: float = 60) -> str:
    """Appelle la brique Studio (audio-séries) et renvoie une chaîne pour le LLM.

    S'authentifie avec le « compte Studio » = la clé de service `STUDIO_KEY` (en-tête
    `X-API-Key`), si elle est configurée ; sinon la brique est en mode ouvert. Dégrade
    proprement (jamais de stacktrace) : brique hors ligne, 401 ou erreur → message clair.
    La production d'épisode appelle des LLM : timeout généreux par défaut.
    """
    base = _base(registre, "studio")
    cle = os.environ.get("STUDIO_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
    except httpx.HTTPError:
        return json.dumps({"ok": False,
                           "message": "La brique Studio est injoignable (hors ligne ou en démarrage)."},
                          ensure_ascii=False)
    if r.status_code == 401:
        return json.dumps({"ok": False,
                           "message": "Le Studio a refusé l'accès (clé de service absente ou invalide). "
                                      "Vérifie que STUDIO_KEY est bien la même côté noyau et côté brique."},
                          ensure_ascii=False)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = r.text[:200]
        return json.dumps({"ok": False,
                           "message": f"Le Studio n'a pas pu traiter la demande (HTTP {r.status_code}) : {detail}"},
                          ensure_ascii=False)
    # 204 (suppression) ou corps vide → succès sans payload.
    if r.status_code == 204 or not r.content:
        return json.dumps({"ok": True}, ensure_ascii=False)
    return json.dumps(r.json(), ensure_ascii=False)


async def _personnages_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                             charge: dict | None = None, params: dict | None = None,
                             timeout: float = 45, brut: bool = False):
    """Appelle la brique Personnages (5900, atelier holistique). Auth via `PERSONNAGES_KEY`
    (X-API-Key) si configurée ; sinon mode ouvert. Dégrade proprement (jamais de stacktrace).
    `brut=True` renvoie le dict parsé (pour chaîner géo→portrait→fiche)."""
    try:
        base = _base(registre, "personnages")
    except RuntimeError:
        msg = {"ok": False, "message": "La brique Personnages (atelier cosmique) est absente du registre du noyau."}
        return msg if brut else json.dumps(msg, ensure_ascii=False)
    cle = os.environ.get("PERSONNAGES_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    erreur = None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
        if r.status_code == 401:
            erreur = {"ok": False, "message": "Personnages a refusé l'accès (PERSONNAGES_KEY)."}
        elif r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            erreur = {"ok": False, "message": f"Personnages HTTP {r.status_code} : {detail}"}
        else:
            data = r.json() if r.content else {"ok": True}
            return data if brut else json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError:
        erreur = {"ok": False,
                  "message": "La brique Personnages (atelier cosmique) est injoignable (hors ligne ou en démarrage)."}
    return erreur if brut else json.dumps(erreur, ensure_ascii=False)


def _empreinte_lignes(empreinte: list) -> list:
    """Aplati l'empreinte holistique ([{cle, valeur, …}]) en lignes lisibles (max 20)."""
    lignes = []
    for e in empreinte or []:
        if isinstance(e, dict):
            cle, val = str(e.get("cle") or "").strip(), str(e.get("valeur") or "").strip()
            ligne = f"{cle} : {val}" if cle and val else (cle or val)
        else:
            ligne = str(e).strip()
        if ligne:
            lignes.append(ligne)
    return lignes[:20]


async def _personnage_holistique(client: httpx.AsyncClient, registre, args: dict) -> str:
    """Crée un personnage holistique (brique 5900) depuis des infos de naissance dictées.

    Génération seule = non destructif (le portrait est déterministe, rien n'est stocké).
    Avec `enregistrer`/`serie_id` = action gardée par `confirme` : on enregistre la fiche
    et/ou on l'importe dans une série du Studio (nom de scène, nom cosmique d'origine gardé).
    Dégrade proprement si une brique est injoignable."""
    prenoms = (args.get("prenoms") or "").strip()
    date_naissance = (args.get("date_naissance") or "").strip()
    if not prenoms or not date_naissance:
        return json.dumps({"ok": False,
                           "message": "Il faut au moins des prénoms et une date de naissance (AAAA-MM-JJ)."},
                          ensure_ascii=False)
    enregistrer = bool(args.get("enregistrer"))
    serie_id = (args.get("serie_id") or "").strip()
    action = enregistrer or bool(serie_id)
    if action and not args.get("confirme"):
        cible = prenoms + (f" → série {serie_id}" if serie_id else " (enregistrer)")
        return _confirmation("créer et ranger le personnage cosmique", cible)

    nom_famille = (args.get("nom") or "").strip()
    nom_complet = (prenoms + (" " + nom_famille if nom_famille else "")).strip()
    ville = (args.get("ville") or "").strip()

    # Géocodage de la ville (optionnel) → latitude / longitude EST-positive
    latitude = longitude = None
    ville_resolue = ville
    if ville:
        g = await _personnages_appel(client, registre, "GET", "/geo",
                                     params={"ville": ville}, timeout=20, brut=True)
        if isinstance(g, dict) and g.get("latitude") is not None:
            latitude, longitude = g.get("latitude"), g.get("longitude")
            ville_resolue = g.get("ville") or ville

    # Portrait cosmique (déterministe — ne stocke rien)
    fiche_in = {"prenoms": prenoms, "nom": nom_famille, "date_naissance": date_naissance,
                "heure_naissance": args.get("heure_naissance") or None,
                "latitude": latitude, "longitude": longitude,
                "utc_offset": args.get("utc_offset")}
    portrait = await _personnages_appel(client, registre, "POST", "/holistique/portrait",
                                        charge=fiche_in, timeout=45, brut=True)
    if not isinstance(portrait, dict) or not portrait.get("portrait"):
        return json.dumps(portrait if isinstance(portrait, dict)
                          else {"ok": False, "message": "Portrait indisponible."}, ensure_ascii=False)

    p = portrait.get("portrait") or {}
    resume = {"ok": True, "prenoms": prenoms, "nom": nom_famille or None,
              "archetype": p.get("archetype"), "forces": p.get("forces"),
              "a_travailler": p.get("faiblesse"),
              "pierre": (p.get("pierre_equilibrage") or {}).get("pierre"),
              "ville": ville_resolue or None}
    if not action:
        return json.dumps(resume, ensure_ascii=False)

    # — Action confirmée : enregistrer et/ou importer dans une série du Studio —
    fiche_id = None
    if enregistrer:
        contexte = {"prenoms": prenoms, "nom": nom_famille, "date": date_naissance,
                    "heure": args.get("heure_naissance") or "", "ville": ville_resolue,
                    "latitude": latitude, "longitude": longitude}
        f = await _personnages_appel(client, registre, "POST", "/fiches", charge={
            "nom": nom_complet, "contexte": contexte,
            "traditions": portrait.get("traditions"), "portrait": p,
            "empreinte": portrait.get("empreinte")}, timeout=30, brut=True)
        if isinstance(f, dict) and f.get("id"):
            resume["fiche_enregistree"] = fiche_id = f["id"]
        else:
            resume["enregistrement"] = f  # message d'échec honnête

    if serie_id:
        nom_scene = (args.get("nom_scene") or "").strip()
        if fiche_id:   # fiche persistée → import par id (le Studio relit la fiche complète)
            imp = await _studio_appel(client, registre, "POST",
                                      f"/series/{serie_id}/personnages/importer-fiche",
                                      charge={"fiche_id": fiche_id, "nom": nom_scene or None},
                                      timeout=30)
        else:          # pas enregistrée → push direct (nom d'origine + archétype + empreinte)
            imp = await _studio_appel(client, registre, "POST",
                                      f"/series/{serie_id}/personnages/importer",
                                      charge={"nom": nom_scene or prenoms,
                                              "nom_naissance": nom_complet,
                                              "archetype": p.get("archetype"),
                                              "empreinte": _empreinte_lignes(portrait.get("empreinte")),
                                              "source": "personnages"}, timeout=30)
        try:
            resume["importe_dans_serie"] = json.loads(imp)
        except (ValueError, TypeError):
            resume["importe_dans_serie"] = imp
    return json.dumps(resume, ensure_ascii=False)


async def _transcription_appel(client: httpx.AsyncClient, registre, methode: str, chemin: str,
                               charge: dict | None = None, params: dict | None = None,
                               timeout: float = 60, brut: bool = False):
    """Appelle la brique Transcription (5980). S'authentifie avec `TRANSCRIPTION_KEY`
    (en-tête `X-API-Key`) si configurée ; sinon mode ouvert. Dégrade proprement (jamais de
    stacktrace). `brut=True` renvoie le dict parsé (pour chaîner transcrire→résumer) ;
    sinon une chaîne JSON pour le LLM. La transcription locale peut être lente : timeout large."""
    base = _base(registre, "transcription")
    cle = os.environ.get("TRANSCRIPTION_KEY", "").strip()
    entetes = {"X-API-Key": cle} if cle else None
    erreur = None
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes, timeout=timeout)
        if r.status_code == 401:
            erreur = {"ok": False, "message": "Transcription a refusé l'accès (TRANSCRIPTION_KEY)."}
        elif r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:  # noqa: BLE001
                detail = r.text[:200]
            erreur = {"ok": False, "message": f"Transcription HTTP {r.status_code} : {detail}"}
        else:
            data = r.json() if r.content else {"ok": True}
            return data if brut else json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError:
        erreur = {"ok": False,
                  "message": "La brique Transcription est injoignable (hors ligne ou en démarrage)."}
    return erreur if brut else json.dumps(erreur, ensure_ascii=False)


async def _etat_briques(client: httpx.AsyncClient, registre) -> dict:
    briques = []
    for nom, manifest in registre.briques.items():
        entree = {"nom": nom, "role": manifest.get("role"), "sante": "inconnu"}
        # Chemin de santé propre à chaque brique (certaines exposent /health, d'autres /sante) :
        # on dérive le chemin de l'url_sante du manifest, et l'hôte du registre.
        url_sante = manifest.get("url_sante") or ""
        chemin = "/" + url_sante.split("/", 3)[-1] if url_sante.count("/") >= 3 else "/sante"
        try:
            r = await client.get(f"{_base(registre, nom)}{chemin}", timeout=4)
            entree["sante"] = "ok" if r.status_code < 400 else "inaccessible"
        except Exception:
            entree["sante"] = "inaccessible"
        briques.append(entree)
    return {"briques": briques, "total": len(briques)}
