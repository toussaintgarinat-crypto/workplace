"""S228 : entretien guidé IA."""
from __future__ import annotations

from types import SimpleNamespace

import app.routers.entretiens as entretiens_mod
from app.serde import entretien


def test_squelette_a_9_qualitatif_et_4_processus():
    familles = [s["famille"] for s in entretiens_mod.SECTIONS]
    assert familles.count("qualitatif") == 9
    assert familles.count("processus") == 4
    assert len(entretiens_mod.SECTIONS) == 13


def test_squelette_categories_qualitatif_s227():
    cats = {s["categorie"] for s in entretiens_mod.SECTIONS if s["famille"] == "qualitatif"}
    assert cats == {
        "organisation", "activites", "clients", "fournisseurs", "outils_utilises",
        "personnel", "contraintes", "objectifs", "problemes_connus",
    }


def test_prochaine_section_renvoie_la_premiere_non_couverte():
    premiere = entretiens_mod.SECTIONS[0]["id"]
    deuxieme = entretiens_mod.SECTIONS[1]["id"]
    assert entretiens_mod._prochaine_section([])["id"] == premiere
    assert entretiens_mod._prochaine_section([premiere])["id"] == deuxieme


def test_prochaine_section_renvoie_none_si_squelette_complet():
    tous = [s["id"] for s in entretiens_mod.SECTIONS]
    assert entretiens_mod._prochaine_section(tous) is None


def test_serde_entretien_camel_case():
    r = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        venture_id="22222222-2222-2222-2222-222222222222",
        section_courante="qualitatif.organisation",
        sections_couvertes=["qualitatif.activites"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=None, created_at=None,
    )
    d = entretien(r)
    assert d["sectionCourante"] == "qualitatif.organisation"
    assert d["sectionsCouvertes"] == ["qualitatif.activites"]
    assert d["ventureId"] == "22222222-2222-2222-2222-222222222222"
    assert d["statut"] == "en_cours"
    assert d["syncErreur"] is None


import uuid as uuidlib
from datetime import datetime, timezone

from app.auth import UserContext, get_current_user
import app.routers.entretiens as entretiens_mod


def _fake_user():
    return UserContext(sub="user-1", nom="Bob", avatar_emoji="🦊", org_id=None)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Fake session générique : une liste de résultats, un par appel .execute() consécutif."""
    def __init__(self, rows_by_call):
        self._rows_by_call = list(rows_by_call)
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows_by_call.pop(0) if self._rows_by_call else []
        return _FakeResult(rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


VID = "11111111-1111-1111-1111-111111111111"


def _mk_venture(**kw):
    from types import SimpleNamespace
    base = dict(id=VID, owner_id="user-1", audit_id=None, profil_entreprise=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_demarrer_cree_un_entretien_si_aucun_en_cours(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    # 1er execute: SELECT venture ; 2e execute: SELECT entretien en_cours (vide)
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], []]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    body = r.json()
    assert body["sectionCourante"] == "qualitatif.organisation"
    assert body["statut"] == "en_cours"
    assert body["rappel"] is None
    assert "organisée" in body["question"]


async def test_demarrer_reprend_un_entretien_existant(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    from types import SimpleNamespace
    existant = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="processus.commercial", sections_couvertes=["qualitatif.organisation"],
        transcript="## commercial\nOn répond au téléphone.", statut="en_cours",
        sync_erreur=None, derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [existant]]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    body = r.json()
    assert body["sectionCourante"] == "processus.commercial"
    assert body["sectionsCouvertes"] == ["qualitatif.organisation"]
    assert "téléphone" in body["rappel"]


async def test_demarrer_404_si_venture_pas_a_soi(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal", lambda: _FakeSession(rows_by_call=[[]]))
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 404


def test_fusionner_qualitatif_est_non_destructif():
    existant = {"organisation": ["SARL, 5 salariés"]}
    fusion = entretiens_mod._fusionner_qualitatif(existant, "organisation", ["Basée à Lyon"])
    assert fusion == {"organisation": ["SARL, 5 salariés", "Basée à Lyon"]}


def test_fusionner_qualitatif_dedoublonne():
    existant = {"activites": ["conseil"]}
    fusion = entretiens_mod._fusionner_qualitatif(existant, "activites", ["conseil", "formation"])
    assert fusion == {"activites": ["conseil", "formation"]}


def test_fusionner_qualitatif_categorie_absente():
    fusion = entretiens_mod._fusionner_qualitatif(None, "clients", ["PME locales"])
    assert fusion == {"clients": ["PME locales"]}


async def test_repondre_section_qualitative_fusionne_et_relance(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    appels = []

    async def _fake_generate(prompt, system=None, **kw):
        appels.append(prompt)
        if len(appels) == 1:
            return '{"valeurs": ["Basée à Lyon"]}'
        return '{"couverte": false, "question": "Combien de salariés au total ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "On est à Lyon"})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "en_cours"
    assert body["sectionCourante"] == "qualitatif.organisation"
    assert body["question"] == "Combien de salariés au total ?"
    assert body["extractionEchouee"] is False


async def test_repondre_section_qualitative_couverte_avance_au_squelette(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise=None)
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["SARL, 5 salariés"]}'
        return '{"couverte": true, "question": null}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "SARL, 5 salariés"})
    body = r.json()
    assert body["sectionCourante"] == "qualitatif.activites"
    assert body["sectionsCouvertes"] == ["qualitatif.organisation"]


async def test_repondre_extraction_llm_incoherente_ne_bloque_pas(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[row], [v]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return "réponse non-JSON du LLM"
        return '{"couverte": false, "question": "Peux-tu préciser ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["extractionEchouee"] is True
    assert body["question"] == "Peux-tu préciser ?"
