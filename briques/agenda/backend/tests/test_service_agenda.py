"""Surface `/service` (S168) — agrégation multi-calendriers + création par défaut.

On appelle les fonctions de route directement avec la session de test (motif
`test_timetree_routes.py`), l'identité étant celle que `get_current_user` produit pour le
dialecte S2S : `{"sub": "perso"}`. Vérifie l'ISO-fonctionnalité vs l'ancien
`core/agenda.lister_evenements` : agrégation de TOUS les calendriers (dont un partagé),
jointure étiquette/couleur, et résolution/création du calendrier par défaut.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from models.orm import Calendar, CalendarMember, Event, Label
from routers import service as S

USER = {"sub": "perso", "service_call": True}
DEBUT = datetime(2026, 7, 14, 0, 0)
FIN = datetime(2026, 7, 21, 0, 0)


async def _cal(db, user_id="perso", name="Perso", is_default=False, color="#111111"):
    c = Calendar(user_id=user_id, name=name, is_default=is_default, color=color)
    db.add(c)
    await db.flush()
    return c


async def _evt(db, cal_id, titre, jour, label_id=None, color=None):
    e = Event(calendar_id=cal_id, title=titre,
              start_at=datetime(2026, 7, jour, 12, 0), end_at=datetime(2026, 7, jour, 13, 0),
              created_by="perso", label_id=label_id, color=color, rappels=[])
    db.add(e)
    await db.flush()
    return e


# ── Agrégation ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agrege_perso_et_partage(db):
    perso = await _cal(db, name="Perso", is_default=True, color="#AAAAAA")
    # Calendrier « TimeTree » d'un autre propriétaire, mais partagé à perso (membre).
    tt = await _cal(db, user_id="autre", name="TimeTree", color="#BBBBBB")
    db.add(CalendarMember(calendar_id=tt.id, user_id="perso", role="viewer"))
    await _evt(db, perso.id, "Dentiste", 15)
    await _evt(db, tt.id, "Anniv (TimeTree)", 16)
    await db.commit()

    evts = await S.service_lister_evenements(debut=DEBUT, fin=FIN, db=db, user=USER)
    titres = {e["title"] for e in evts}
    assert titres == {"Dentiste", "Anniv (TimeTree)"}      # les DEUX sources agrégées
    par_titre = {e["title"]: e for e in evts}
    assert par_titre["Anniv (TimeTree)"]["calendrier"] == "TimeTree"
    assert par_titre["Dentiste"]["couleur"] == "#AAAAAA"    # repli couleur du calendrier


@pytest.mark.asyncio
async def test_jointure_etiquette_et_couleur(db):
    perso = await _cal(db, name="Perso", is_default=True, color="#AAAAAA")
    lab = Label(calendar_id=perso.id, name="Boulot", color="#FF0000")
    db.add(lab)
    await db.flush()
    await _evt(db, perso.id, "Réunion", 15, label_id=lab.id, color="#abcdef")   # étiquette
    await _evt(db, perso.id, "Libre", 16, label_id=None, color="#abcdef")       # couleur libre
    await _evt(db, perso.id, "Vide", 17, label_id=None, color=None)             # repli calendrier
    await db.commit()

    par_titre = {e["title"]: e for e in
                 await S.service_lister_evenements(debut=DEBUT, fin=FIN, db=db, user=USER)}
    # Priorité couleur : étiquette > couleur libre de l'événement > couleur du calendrier.
    assert par_titre["Réunion"]["etiquette"] == "Boulot"
    assert par_titre["Réunion"]["couleur"] == "#FF0000"
    assert par_titre["Libre"]["etiquette"] is None
    assert par_titre["Libre"]["couleur"] == "#abcdef"
    assert par_titre["Vide"]["couleur"] == "#AAAAAA"


@pytest.mark.asyncio
async def test_filtre_hors_fenetre_exclu(db):
    perso = await _cal(db, name="Perso", is_default=True)
    await _evt(db, perso.id, "Dans la fenêtre", 15)
    await _evt(db, perso.id, "Trop tard", 25)      # au-delà de FIN (21)
    await db.commit()

    evts = await S.service_lister_evenements(debut=DEBUT, fin=FIN, db=db, user=USER)
    assert {e["title"] for e in evts} == {"Dans la fenêtre"}


@pytest.mark.asyncio
async def test_agrege_deplie_recurrence(db):
    perso = await _cal(db, name="Perso", is_default=True)
    m = Event(calendar_id=perso.id, title="Hebdo", created_by="perso", rappels=[10],
              start_at=datetime(2026, 7, 14, 12, 0), end_at=datetime(2026, 7, 14, 13, 0),
              recurrence_rule="FREQ=DAILY", exdates=[])
    db.add(m); await db.commit()
    evts = await S.service_lister_evenements(debut=DEBUT, fin=FIN, db=db, user=USER)
    hebdo = [e for e in evts if e["title"] == "Hebdo"]
    assert len(hebdo) == 7                                  # 14→20 juillet inclus
    assert {e["occurrence_start"][:10] for e in hebdo} == {
        f"2026-07-{d:02d}" for d in range(14, 21)}
    assert all(e["recurrent"] and e["participants"] is not None for e in hebdo)


# ── Création (calendrier par défaut) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_creer_sans_calendrier_cree_le_defaut(db):
    # Aucun calendrier n'existe → la brique crée « Perso » elle-même.
    corps = S.EvenementServiceIn(titre="Déjeuner", debut=datetime(2026, 7, 15, 12, 30),
                                 fin=datetime(2026, 7, 15, 13, 30), lieu="Bistrot")
    evt = await S.service_creer_evenement(corps=corps, db=db, user=USER)
    assert evt.title == "Déjeuner" and evt.location == "Bistrot"
    cal = await db.get(Calendar, evt.calendar_id)
    assert cal.name == "Perso" and cal.is_default is True


@pytest.mark.asyncio
async def test_creer_utilise_le_calendrier_marque_defaut(db):
    await _cal(db, name="Autre", is_default=False)
    defaut = await _cal(db, name="Mon défaut", is_default=True)
    await db.commit()
    corps = S.EvenementServiceIn(titre="RDV", debut=datetime(2026, 7, 15, 9, 0),
                                 fin=datetime(2026, 7, 15, 10, 0))
    evt = await S.service_creer_evenement(corps=corps, db=db, user=USER)
    assert evt.calendar_id == defaut.id


@pytest.mark.asyncio
async def test_creer_refuse_fin_avant_debut(db):
    from fastapi import HTTPException
    corps = S.EvenementServiceIn(titre="Incohérent", debut=datetime(2026, 7, 15, 14, 0),
                                 fin=datetime(2026, 7, 15, 13, 0))
    with pytest.raises(HTTPException) as exc:
        await S.service_creer_evenement(corps=corps, db=db, user=USER)
    assert exc.value.status_code == 422


# ── Déplacer / rappels (PATCH /service/events/{id}) ──────────────────────────

@pytest.mark.asyncio
async def test_deplacer_change_les_dates(db):
    perso = await _cal(db, is_default=True)
    e = await _evt(db, perso.id, "RDV", 15)
    await db.commit()
    corps = S.EvenementPatchIn(debut=datetime(2026, 7, 16, 9, 0), fin=datetime(2026, 7, 16, 10, 0))
    out = await S.service_modifier_evenement(event_id=e.id, corps=corps, db=db, user=USER)
    assert out.start_at.hour == 9 and out.start_at.day == 16


@pytest.mark.asyncio
async def test_definir_rappels_puis_effacer(db):
    perso = await _cal(db, is_default=True)
    e = await _evt(db, perso.id, "RDV", 15)
    await db.commit()
    out = await S.service_modifier_evenement(
        event_id=e.id, corps=S.EvenementPatchIn(rappels=[30, 1440]), db=db, user=USER)
    assert out.rappels == [30, 1440]
    # Liste vide = effacement explicite (≠ non fourni).
    out2 = await S.service_modifier_evenement(
        event_id=e.id, corps=S.EvenementPatchIn(rappels=[]), db=db, user=USER)
    assert out2.rappels == []


@pytest.mark.asyncio
async def test_patch_sans_champ_refuse(db):
    perso = await _cal(db, is_default=True)
    e = await _evt(db, perso.id, "RDV", 15)
    await db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await S.service_modifier_evenement(event_id=e.id, corps=S.EvenementPatchIn(), db=db, user=USER)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_modifier_event_inexistant_404(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await S.service_modifier_evenement(
            event_id="fantome", corps=S.EvenementPatchIn(titre="x"), db=db, user=USER)
    assert exc.value.status_code == 404


# ── Supprimer (DELETE /service/events/{id}) ──────────────────────────────────

@pytest.mark.asyncio
async def test_supprimer_evenement(db):
    perso = await _cal(db, is_default=True)
    e = await _evt(db, perso.id, "À annuler", 15)
    await db.commit()
    await S.service_supprimer_evenement(event_id=e.id, db=db, user=USER)
    assert await db.get(Event, e.id) is None


# ── Calendriers + invitations ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lister_et_creer_calendrier(db):
    await _cal(db, name="Perso", is_default=True)
    await db.commit()
    cree = await S.service_creer_calendrier(
        corps=S.CalendrierServiceIn(nom="Famille", couleur="#123456"), db=db, user=USER)
    assert cree["nom"] == "Famille" and cree["couleur"] == "#123456"
    listing = await S.service_lister_calendriers(db=db, user=USER)
    assert {c["nom"] for c in listing} == {"Perso", "Famille"}


@pytest.mark.asyncio
async def test_inviter_renvoie_un_lien(db, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "AGENDA_URL_PUBLIQUE", "https://agenda.exemple.fr", raising=False)
    cal = await _cal(db, name="Famille", is_default=False)
    await db.commit()

    class _Req:  # request.base_url n'est pas utilisé quand AGENDA_URL_PUBLIQUE est posée
        base_url = "http://interne:8400/"
    inv = await S.service_inviter(calendar_id=cal.id, corps=S.InvitationServiceIn(role="editor"),
                                  request=_Req(), db=db, user=USER)
    assert inv["role"] == "editor"
    assert inv["lien"] == f"https://agenda.exemple.fr/invitations/{inv['token']}/page"

