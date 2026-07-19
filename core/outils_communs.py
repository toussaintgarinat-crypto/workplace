"""Plomberie partagée des outils (S115) : helpers HTTP sans état appelés par les
modules de dispatch par domaine (outils_domaines) et par la façade outils.py.
Aucune logique de catalogue/capacités ici (elle reste dans outils.py).
"""
import asyncio
import json
import os
import uuid
import httpx
import contexte_tenant
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
    """En-têtes de service pour piloter une brique au nom de l'appelant (S167).

    - ``{BRIQUE}_KEY`` → ``X-API-Key`` : prouve qu'on a le droit d'emprunter la surface
      ``/service`` (motif muscle.py). Sans clé, la brique reste en mode ouvert.
    - ``ADMIN_COMPTE_ID`` (défaut ``admin``) → ``X-Compte-Id`` : identité de l'appelant.
      La brique lit le ``role`` de ce compte EN BASE pour décider du périmètre (admin =
      accès total ; tenant = ses ressources). Mono-user aujourd'hui → toujours l'admin ;
      multi-user demain → l'id de l'utilisateur courant, sans rien changer côté brique.
      Cf. ADR docs/decisions/2026-07-13-surface-de-service-role-admin.md.
    """
    entetes: dict = {"X-Compte-Id": os.environ.get("ADMIN_COMPTE_ID", "admin")}
    cle = os.environ.get(f"{brique.upper()}_KEY")
    if cle:
        entetes["X-API-Key"] = cle
    # S182 « chacun son agenda » : les outils de l'assistant empruntent la surface
    # /service ; on forwarde l'identité de l'utilisateur connecté (contexte de tenant) en
    # X-User-Id pour que l'agenda serve SES données au lieu du pin « perso ». Ciblé sur
    # l'agenda (seule brique qui honore X-User-Id derrière AGENDA_KEY) ; les autres
    # briques ignorent cet en-tête.
    if brique.lower() == "agenda":
        entetes.update(contexte_tenant.entetes_agenda())
    return entetes


def _url_dynamique(cap: dict, args: dict) -> str:
    """URL de la capacité, avec substitution des params de chemin ``{x}`` depuis les args."""
    url = cap["url"]
    if "{" in url:
        for k, v in args.items():
            url = url.replace("{" + k + "}", str(v))
    return url


ASYNC_TIMEOUT = float(os.environ.get("OUTILS_ASYNC_TIMEOUT", "600"))
ASYNC_POLL = float(os.environ.get("OUTILS_ASYNC_POLL", "5"))


async def _poll_async(poll_url: str, headers: dict | None, brique: str,
                      job_id: str) -> str:
    async with httpx.AsyncClient(timeout=None, headers=headers) as c:
        while True:
            r = await c.request("GET", poll_url, headers=headers)
            try:
                data = r.json()
            except ValueError:
                return json.dumps({"ok": False, "brique": brique,
                                   "message": f"Poll {poll_url} a renvoyé un corps non JSON "
                                              f"(HTTP {r.status_code})."}, ensure_ascii=False)
            statut = data.get("statut")
            if statut == "termine":
                return json.dumps(data.get("resultat") or data, ensure_ascii=False)
            if statut == "erreur":
                return json.dumps({"ok": False, "brique": brique,
                                   "message": data.get("erreur") or "job en erreur"},
                                  ensure_ascii=False)
            await asyncio.sleep(ASYNC_POLL)


async def _appel_dynamique(client, cap: dict, args: dict) -> str:
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
        r = await client.request(cap["methode"], url, json=charge, params=charge, headers=entetes)
    # ── Branche async (S179) : 202 sur cap async → on poll ──
    if cap.get("async") and r.status_code == 202:
        try:
            body = r.json()
        except ValueError:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": "202 sans corps JSON."}, ensure_ascii=False)
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": "202 reçu sans job_id — impossible de poller."},
                              ensure_ascii=False)
        poll_chemin = (cap.get("poll_chemin") or "/jobs/{id}").replace("{id}", str(job_id))
        base = cap["url"].rsplit(cap["chemin"], 1)[0]
        poll_url = base + poll_chemin
        async_timeout = float(os.environ.get("OUTILS_ASYNC_TIMEOUT", str(ASYNC_TIMEOUT)))
        try:
            return await asyncio.wait_for(
                _poll_async(poll_url, entetes, cap["brique"], job_id),
                timeout=async_timeout,
            )
        except asyncio.TimeoutError:
            return json.dumps({"ok": False, "brique": cap["brique"],
                               "message": f"Délai dépassé ({async_timeout:.0f}s). Job "
                                          f"toujours en cours — interroge GET {poll_url} "
                                          "plus tard.",
                               "job_id": job_id}, ensure_ascii=False)
    # ── Branche sync (comportement S64 inchangé) ──
    if r.status_code >= 400:
        return json.dumps({"ok": False, "brique": cap["brique"],
                           "message": f"Brique « {cap['brique']} » a refusé ({r.status_code})."},
                          ensure_ascii=False)
    try:
        return json.dumps(r.json(), ensure_ascii=False)
    except ValueError:
        texte = (r.text or "").strip()
        if not texte:
            return json.dumps({"ok": True, "brique": cap["brique"], "status": r.status_code},
                              ensure_ascii=False)
        return texte[:1000]


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
    # Propage l'identité de l'utilisateur courant (S121) : l'adaptateur Forge consomme
    # `X-Forge-User-Token` pour agir AU NOM de l'utilisateur ; sans token (mono-user), dict
    # vide → repli sur le token de service côté adaptateur (flux S17/S24 inchangé).
    entetes = contexte_tenant.entetes_forge()
    try:
        r = await client.request(methode, f"{base}{chemin}", json=charge, params=params,
                                  headers=entetes or None, timeout=timeout)
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


async def _personnages_fiches_lister(client: httpx.AsyncClient, registre) -> str:
    """Liste les fiches holistiques enregistrées (GET /fiches)."""
    data = await _personnages_appel(client, registre, "GET", "/fiches", timeout=15, brut=True)
    if not isinstance(data, list):
        return json.dumps(data if isinstance(data, dict)
                          else {"ok": False, "message": "Réponse inattendue de la brique personnages."},
                          ensure_ascii=False)
    resume = [{"id": f.get("id"), "nom": f.get("nom"), "categorie": f.get("categorie"),
               "archetype": (f.get("portrait") or {}).get("archetype")} for f in data]
    return json.dumps({"ok": True, "fiches": resume, "total": len(resume)}, ensure_ascii=False)


async def _personnage_importer_serie(client: httpx.AsyncClient, registre, args: dict) -> str:
    """Importe une fiche holistique existante dans une série du Studio."""
    fiche_id = (args.get("fiche_id") or "").strip()
    serie_id = (args.get("serie_id") or "").strip()
    if not fiche_id or not serie_id:
        return json.dumps({"ok": False, "message": "fiche_id et serie_id sont requis."}, ensure_ascii=False)
    if not args.get("confirme"):
        return _confirmation("importer le personnage dans la série", f"fiche {fiche_id} → série {serie_id}")
    nom_scene = (args.get("nom_scene") or "").strip() or None
    charge = {"fiche_id": fiche_id}
    if nom_scene:
        charge["nom"] = nom_scene
    return await _studio_appel(client, registre, "POST",
                               f"/series/{serie_id}/personnages/importer-fiche",
                               charge=charge, timeout=30)


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
