"""S135 — logique pure : sérialiseurs comms/intégrations + helpers routeurs.

Pas de DB : on instancie des lignes factices (SimpleNamespace) et on vérifie la
parité de forme avec le Bun (camelCase, dates ISO ...Z, sous-ensembles de colonnes,
champs TEXT JSON renvoyés bruts, masquage authToken, meta plateforme, etc.).
"""

import datetime
import types
import uuid

from app.routers.calendar import _parse_dt
from app.routers.incidents import _SEVERITES, _STATUTS
from app.routers.sentinel_rgpd import RGPD_CHECKLIST
from app.routers.social import PLATFORMS, _with_meta
from app.serde import (
    agenda_event, document_full, document_list, imap_config_min,
    imap_config_public, imap_email, incident, keybinding, mcp_server,
    saved_filter, social_account,
)

DT = datetime.datetime(2026, 5, 31, 9, 30, 0)
ISO = "2026-05-31T09:30:00.000Z"


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── keybinding ────────────────────────────────────────────────────────────

def test_keybinding_serde():
    uid = uuid.uuid4()
    out = keybinding(_ns(id=uid, user_id="u1", touche="ctrl+k", action="palette", created_at=DT))
    assert out == {"id": str(uid), "userId": "u1", "touche": "ctrl+k",
                   "action": "palette", "createdAt": ISO}


# ── saved_filter : filtre TEXT JSON brut ───────────────────────────────────

def test_saved_filter_keeps_filtre_raw():
    uid = uuid.uuid4()
    out = saved_filter(_ns(id=uid, user_id="u1", org_id=None, nom="f",
                           contexte="crm", filtre='{"statut":"gagne"}', created_at=DT))
    assert out["filtre"] == '{"statut":"gagne"}'  # non parsé (parité Drizzle)
    assert out["orgId"] is None and out["contexte"] == "crm"


# ── imap : sous-ensembles de colonnes (pas de mot de passe) ─────────────────

def test_imap_config_public_six_fields_no_password():
    uid = uuid.uuid4()
    out = imap_config_public(_ns(id=uid, host="imap.x", port=993, email="a@x",
                                 actif=True, created_at=DT, password="SECRET"))
    assert set(out) == {"id", "host", "port", "email", "actif", "createdAt"}
    assert "password" not in out


def test_imap_config_min_four_fields():
    uid = uuid.uuid4()
    out = imap_config_min(_ns(id=uid, host="imap.x", email="a@x", actif=True))
    assert set(out) == {"id", "host", "email", "actif"}


def test_imap_email_serde():
    uid, cid = uuid.uuid4(), uuid.uuid4()
    out = imap_email(_ns(id=uid, config_id=cid, message_id="m1", sujet="hi",
                         expediteur="b@x", corps="body", lu=False, created_at=DT))
    assert out["configId"] == str(cid) and out["messageId"] == "m1"
    assert out["lu"] is False and out["createdAt"] == ISO


# ── incident ────────────────────────────────────────────────────────────────

def test_incident_serde_with_resolved():
    uid, pid = uuid.uuid4(), uuid.uuid4()
    out = incident(_ns(id=uid, pole_id=pid, user_id="u1", titre="down", description="d",
                       severite="critique", statut="resolu", resolved_at=DT,
                       created_at=DT, updated_at=DT))
    assert out["poleId"] == str(pid) and out["severite"] == "critique"
    assert out["resolvedAt"] == ISO


def test_incident_resolved_null():
    out = incident(_ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u1", titre="t",
                       description=None, severite="basse", statut="ouvert",
                       resolved_at=None, created_at=DT, updated_at=DT))
    assert out["resolvedAt"] is None


def test_incident_severites_statuts_sets():
    assert _SEVERITES == {"critique", "haute", "moyenne", "basse"}
    assert _STATUTS == {"ouvert", "en_cours", "resolu", "ferme"}


# ── agenda_event ──────────────────────────────────────────────────────────

def test_agenda_event_serde():
    uid = uuid.uuid4()
    out = agenda_event(_ns(id=uid, user_id="u1", org_id=None, titre="rdv",
                           description=None, date_debut=DT, date_fin=DT, pole="ops",
                           google_id=None, created_at=DT))
    assert out["dateDebut"] == ISO and out["dateFin"] == ISO
    assert out["pole"] == "ops" and out["googleId"] is None


# ── _parse_dt (calendar) ────────────────────────────────────────────────────

def test_parse_dt_z_suffix_to_naive_utc():
    dt = _parse_dt("2026-05-31T09:30:00.000Z")
    assert dt == DT and dt.tzinfo is None


def test_parse_dt_with_offset_normalized_utc():
    dt = _parse_dt("2026-05-31T11:30:00+02:00")
    assert dt == DT and dt.tzinfo is None


def test_parse_dt_none_and_garbage():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt("pas-une-date") is None


# ── social : meta plateforme ────────────────────────────────────────────────

def test_social_account_config_raw_no_meta():
    out = social_account(_ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u1",
                             platform="linkedin", nom="page", config='{"k":1}',
                             actif=True, created_at=DT))
    assert out["config"] == '{"k":1}'  # brut
    assert "meta" not in out  # ajouté par le routeur


def test_with_meta_known_platform():
    row = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u1", platform="instagram",
              nom="ig", config=None, actif=True, created_at=DT)
    out = _with_meta(row, {"label": "?", "emoji": "🌐", "color": "#64748b"})
    assert out["meta"] == {"label": "Instagram", "emoji": "📸", "color": "#e1306c"}


def test_with_meta_unknown_platform_uses_default():
    default = {"label": "myspace", "emoji": "🌐", "color": "#64748b"}
    row = _ns(id=uuid.uuid4(), pole_id=uuid.uuid4(), user_id="u1", platform="myspace",
              nom="m", config=None, actif=True, created_at=DT)
    assert _with_meta(row, default)["meta"] == default


def test_platforms_count_and_shape():
    assert len(PLATFORMS) == 10
    for v in PLATFORMS.values():
        assert {"label", "emoji", "color"} == set(v)


# ── mcp_server : authToken exposé par le serde (masqué côté routeur) ────────

def test_mcp_server_serde_exposes_token_raw():
    out = mcp_server(_ns(id=uuid.uuid4(), user_id="u1", org_id=None, venture_id=None,
                         pole_id=None, nom="s", url="https://m", auth_type="bearer",
                         auth_token="SECRET", actif=True, created_at=DT))
    assert out["authToken"] == "SECRET"  # le routeur masque, pas le serde
    assert out["authType"] == "bearer"


# ── documents : full vs list (sans contenu) ─────────────────────────────────

def test_document_full_has_contenu():
    out = document_full(_ns(id=uuid.uuid4(), user_id="u1", pole_id=None, session_id=None,
                            nom="doc", type="pdf", contenu="hello", analyse="résumé",
                            taille=5, created_at=DT))
    assert out["contenu"] == "hello" and out["taille"] == 5


def test_document_list_omits_contenu():
    out = document_list(_ns(id=uuid.uuid4(), nom="doc", type="pdf", analyse="r",
                            taille=5, pole_id=None, created_at=DT))
    assert "contenu" not in out
    assert set(out) == {"id", "nom", "type", "analyse", "taille", "poleId", "createdAt"}


# ── sentinel-rgpd : checklist + calcul du score ─────────────────────────────

def test_rgpd_checklist_ten_items_with_articles():
    assert len(RGPD_CHECKLIST) == 10
    for item in RGPD_CHECKLIST:
        assert {"id", "label", "articles"} <= set(item)
        assert isinstance(item["articles"], list) and item["articles"]


def test_rgpd_score_formula():
    # 5 conformes sur 10 → 50
    checklist = {RGPD_CHECKLIST[i]["id"]: True for i in range(5)}
    status = [{**it, "conforme": checklist.get(it["id"], False)} for it in RGPD_CHECKLIST]
    conformes = sum(1 for i in status if i["conforme"])
    assert round((conformes / len(RGPD_CHECKLIST)) * 100) == 50
