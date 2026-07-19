"""Routes « agenda » du Cœur (extrait de main.py, S114).

Agenda : événements, TimeTree, Google, documents, commentaires, étiquettes.
"""
import json
import logging
import urllib.parse
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from etat import registre
import agenda
import auth

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/agenda/invitation/{token}", tags=["agenda"])
async def agenda_accepter_invitation(token: str, request: Request):
    """Accepte une invitation à un agenda partagé (S182b) — c'est le lien transmis à
    l'invité, sous le modèle « login unique au Cœur » : pas de page/PKCE côté brique.

    Non connecté ⇒ redirige vers le login du Cœur avec retour ici (`next`), puis l'invité
    revient et l'acceptation se fait sous SON identité de session. Connecté ⇒ accepte via
    le proxy (X-User-Id de session) et renvoie au dashboard, onglet Agenda."""
    if not auth.sub_session_optionnel(request):
        cible = "/agenda/invitation/" + urllib.parse.quote(token)
        return RedirectResponse(f"/auth/login?next={urllib.parse.quote(cible)}", status_code=303)
    try:
        await agenda.accepter_invitation(registre, token)
        return RedirectResponse("/dashboard#agenda", status_code=303)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/accepter_invitation : %s", e)
        return RedirectResponse("/dashboard#agenda?invitation=echec", status_code=303)


@router.get("/agenda/evenements", tags=["agenda"])
async def agenda_evenements(debut: str | None = None, fin: str | None = None):
    """Événements de l'agenda personnel (proxy de la brique agenda) pour l'onglet Agenda."""
    try:
        return {"evenements": await agenda.lister_evenements(registre, debut, fin)}
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/evenements : %s", e)
        return {"evenements": [], "detail": str(e)}


@router.patch("/agenda/evenements/{event_id}/rappels", tags=["agenda"])
async def agenda_definir_rappels(event_id: str, request: Request):
    """Définit les rappels d'un événement (minutes avant le début) depuis le dashboard."""
    try:
        corps = await request.json()
        rappels = [int(m) for m in (corps.get("rappels") or [])]
        evt = await agenda.definir_rappels(registre, event_id, rappels)
        return {"ok": True, "rappels": evt.get("rappels") or []}
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/definir_rappels : %s", e)
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=502)


# ── Pont TimeTree (lecture seule, non officiel) — proxys pour le dashboard ────

@router.get("/agenda/timetree/status", tags=["agenda"])
async def agenda_timetree_status():
    try:
        return await agenda.timetree_etat(registre)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/timetree_status : %s", e)
        return {"connected": False, "detail": str(e)}


@router.post("/agenda/timetree/connect", tags=["agenda"])
async def agenda_timetree_connect(request: Request):
    corps = await request.json()
    return await agenda.timetree_connecter(
        registre, corps.get("email", ""), corps.get("password", ""), corps.get("calendar_id"))


@router.post("/agenda/timetree/select", tags=["agenda"])
async def agenda_timetree_select(request: Request):
    corps = await request.json()
    try:
        return await agenda.timetree_choisir_calendrier(registre, corps.get("calendar_id", ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/timetree_select : %s", e)
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=502)


@router.post("/agenda/timetree/sync", tags=["agenda"])
async def agenda_timetree_sync():
    return await agenda.timetree_synchroniser(registre)


@router.delete("/agenda/timetree/disconnect", tags=["agenda"])
async def agenda_timetree_disconnect():
    return {"disconnected": await agenda.timetree_deconnecter(registre)}


# ── Pont Google Agenda (consenti, lecture seule, OAuth) — proxys dashboard ────

@router.get("/agenda/google/status", tags=["agenda"])
async def agenda_google_status():
    try:
        return await agenda.google_etat(registre)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/google_status : %s", e)
        return {"connected": False, "detail": str(e)}


@router.get("/agenda/google/connect", tags=["agenda"])
async def agenda_google_connect():
    """URL de consentement Google à ouvrir côté navigateur (ou erreur si non configuré)."""
    try:
        return await agenda.google_url_consentement(registre)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/google_connect : %s", e)
        return {"ok": False, "erreur": str(e)}


@router.post("/agenda/google/sync", tags=["agenda"])
async def agenda_google_sync(debut: str | None = None, fin: str | None = None):
    return await agenda.google_synchroniser(registre, debut, fin)


@router.delete("/agenda/google/disconnect", tags=["agenda"])
async def agenda_google_disconnect():
    return {"disconnected": await agenda.google_deconnecter(registre)}


# ── Agenda « façon TimeTree » : calendriers, CRUD événements, documents, commentaires ──

@router.get("/agenda/calendriers", tags=["agenda"])
async def agenda_calendriers():
    """Calendriers accessibles (perso + Google + TimeTree + partagés) pour la vue calendrier."""
    try:
        return {"calendriers": await agenda.lister_agendas(registre)}
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/calendriers : %s", e)
        return {"calendriers": [], "detail": str(e)}


@router.post("/agenda/calendriers", tags=["agenda"])
async def agenda_creer_calendrier(request: Request):
    """Crée un agenda partageable au nom de l'utilisateur de session (S182b) : il en est
    owner et pourra y inviter des personnes. Corps : {nom, couleur?, description?}."""
    corps = await request.json()
    nom = (corps.get("nom") or corps.get("name") or "").strip()
    if not nom:
        return JSONResponse({"detail": "nom requis"}, status_code=400)
    try:
        return await agenda.creer_agenda(registre, nom, corps.get("couleur") or corps.get("color"),
                                         corps.get("description"))
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/creer_calendrier : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.post("/agenda/calendriers/{calendar_id}/invitations", tags=["agenda"])
async def agenda_inviter(calendar_id: str, request: Request):
    """Génère un lien d'invitation à un agenda partagé (owner requis côté brique).
    Corps : {role?: viewer|editor, expire_heures?, email?}. Renvoie l'invitation + le lien."""
    corps = await request.json()
    try:
        inv = await agenda.creer_invitation(
            registre, calendar_id,
            role=corps.get("role") or "viewer",
            expire_heures=corps.get("expire_heures", 72),
            email=corps.get("email"))
        return inv
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/inviter : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.post("/agenda/evenements", tags=["agenda"])
async def agenda_creer(request: Request):
    """Crée un événement (champs bruts brique : title, start_at, end_at, location,
    description, color, all_day, rappels ; calendar_id facultatif)."""
    corps = await request.json()
    cal = corps.pop("calendar_id", None) or None
    try:
        return await agenda.creer_evenement_dans(registre, cal, corps)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/creer : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.patch("/agenda/evenements/{event_id}", tags=["agenda"])
async def agenda_modifier(event_id: str, request: Request):
    """Met à jour un événement (PATCH partiel)."""
    corps = await request.json()
    try:
        return await agenda.modifier_evenement(registre, event_id, corps)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/modifier : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.delete("/agenda/evenements/{event_id}", tags=["agenda"])
async def agenda_supprimer(event_id: str):
    return {"supprime": await agenda.supprimer_evenement(registre, event_id)}


@router.get("/agenda/evenements/{event_id}/documents", tags=["agenda"])
async def agenda_documents(event_id: str):
    return {"documents": await agenda.lister_documents(registre, event_id)}


@router.post("/agenda/evenements/{event_id}/documents", tags=["agenda"])
async def agenda_document_upload(event_id: str, file: UploadFile = File(...)):
    try:
        octets = await file.read()
        return await agenda.televerser_document(
            registre, event_id, file.filename or "fichier", octets, file.content_type)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/document_upload : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.get("/agenda/documents/{att_id}", tags=["agenda"])
async def agenda_document_download(att_id: str):
    octets, nom, mt = await agenda.telecharger_document(registre, att_id)
    if octets is None:
        return JSONResponse({"detail": "introuvable"}, status_code=404)
    return Response(content=octets, media_type=mt,
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@router.delete("/agenda/documents/{att_id}", tags=["agenda"])
async def agenda_document_delete(att_id: str):
    return {"supprime": await agenda.supprimer_document(registre, att_id)}


@router.get("/agenda/evenements/{event_id}/commentaires", tags=["agenda"])
async def agenda_commentaires(event_id: str):
    return {"commentaires": await agenda.lister_commentaires(registre, event_id)}


@router.post("/agenda/evenements/{event_id}/commentaires", tags=["agenda"])
async def agenda_commentaire_ajouter(event_id: str, request: Request):
    corps = await request.json()
    contenu = (corps.get("contenu") or corps.get("content") or "").strip()
    if not contenu:
        return JSONResponse({"detail": "commentaire vide"}, status_code=422)
    try:
        return await agenda.ajouter_commentaire(registre, event_id, contenu)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/commentaire_ajouter : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.delete("/agenda/commentaires/{comment_id}", tags=["agenda"])
async def agenda_commentaire_supprimer(comment_id: str):
    return {"supprime": await agenda.supprimer_commentaire(registre, comment_id)}


# ── Étiquettes nommées (catégories) — proxys pour la vue calendrier ──────────

@router.get("/agenda/calendriers/{calendar_id}/etiquettes", tags=["agenda"])
async def agenda_etiquettes(calendar_id: str):
    """Étiquettes nommées d'un calendrier (pour le sélecteur et la légende)."""
    try:
        return {"etiquettes": await agenda.lister_etiquettes(registre, calendar_id)}
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/etiquettes : %s", e)
        return {"etiquettes": [], "detail": str(e)}


@router.post("/agenda/calendriers/{calendar_id}/etiquettes", tags=["agenda"])
async def agenda_etiquette_creer(calendar_id: str, request: Request):
    corps = await request.json()
    nom = (corps.get("name") or corps.get("nom") or "").strip()
    if not nom:
        return JSONResponse({"detail": "nom requis"}, status_code=422)
    try:
        return await agenda.creer_etiquette(registre, calendar_id, nom,
                                            corps.get("color") or corps.get("couleur"))
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/etiquette_creer : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.patch("/agenda/etiquettes/{label_id}", tags=["agenda"])
async def agenda_etiquette_modifier(label_id: str, request: Request):
    corps = await request.json()
    try:
        return await agenda.modifier_etiquette(registre, label_id, corps)
    except Exception as e:  # noqa: BLE001
        logger.warning("agenda/etiquette_modifier : %s", e)
        return JSONResponse({"detail": str(e)}, status_code=502)


@router.delete("/agenda/etiquettes/{label_id}", tags=["agenda"])
async def agenda_etiquette_supprimer(label_id: str):
    return {"supprime": await agenda.supprimer_etiquette(registre, label_id)}
