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
        self.execute_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        self.execute_count += 1
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
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

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
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

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
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

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


async def test_repondre_extraction_json_valide_mais_pas_un_objet_ne_bloque_pas(client, app, monkeypatch):
    """Revue post-Task 4, Finding 1 : le LLM peut renvoyer un JSON syntaxiquement
    valide mais qui n'est pas un objet (liste, null, nombre). `.get("valeurs")`
    planterait en AttributeError si non gardé — doit dégrader comme un
    JSONDecodeError, jamais un 500."""
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '["Lyon"]'  # JSON valide, mais pas un objet
        return '{"couverte": false, "question": "Peux-tu préciser ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["extractionEchouee"] is True
    assert body["question"] == "Peux-tu préciser ?"


async def test_repondre_extraction_json_null_ne_bloque_pas(client, app, monkeypatch):
    """Même garde, variante `null` (autre forme de JSON valide non-objet)."""
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return "null"
        return '{"couverte": false, "question": "Peux-tu préciser ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["extractionEchouee"] is True


async def test_repondre_decision_json_valide_mais_pas_un_objet_ne_bloque_pas(client, app, monkeypatch):
    """Même garde côté bloc décision : `[true]` est un JSON valide non-objet."""
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["Basée à Lyon"]}'
        return '[true]'  # JSON valide, mais pas un objet

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "en_cours"
    assert body["question"] == "Peux-tu préciser ?"


async def test_repondre_generate_text_leve_exception_ne_bloque_pas(client, app, monkeypatch):
    """Revue post-Task 4, Finding 1 : generate_text() peut lever (réseau/timeout/
    quota/fournisseur) — ça ne doit jamais 500 le tour, doit dégrader comme un
    échec d'extraction."""
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        raise TimeoutError("gateway indisponible")

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "..."})
    assert r.status_code == 200
    body = r.json()
    assert body["extractionEchouee"] is True
    assert body["question"] == "Peux-tu préciser ?"


async def test_repondre_404_ownership_verifiee_avant_lecture_entretien(client, app, monkeypatch):
    """Revue post-Task 4, Finding 2 : ownership doit être vérifiée AVANT toute
    lecture d'Entretiens (table sans owner_id) — une venture non possédée doit
    renvoyer 404 « Not found » sans même interroger Entretiens, quel que soit
    l'état d'entretien réel de cette venture (fuite cross-tenant sinon)."""
    app.dependency_overrides[get_current_user] = _fake_user
    sessions = []

    def _make_session():
        sess = _FakeSession(rows_by_call=[[]])  # SELECT Ventures ne renvoie rien (pas à soi)
        sessions.append(sess)
        return sess

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make_session)
    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "x"})
    assert r.status_code == 404
    assert r.json()["error"] == "Not found"
    # Une seule requête exécutée (Ventures) — Entretiens jamais touché : preuve que
    # l'ordre est bien ownership-first (sinon Entretiens serait interrogé avant).
    assert sessions[0].execute_count == 1


async def test_repondre_404_aucun_entretien_en_cours_meme_detail_generique(client, app, monkeypatch):
    """Venture possédée, mais aucun entretien en_cours : même detail générique
    « Not found » que le cas ownership (pas de message distinctif qui révélerait
    l'état d'entretien à qui n'y a pas droit — et ici l'appelant a bien le droit,
    mais le contrat de message reste uniforme)."""
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], []]))
    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "x"})
    assert r.status_code == 404
    assert r.json()["error"] == "Not found"


async def test_repondre_section_processus_accumule_le_transcript(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="processus.commercial", sections_couvertes=list(
            s["id"] for s in entretiens_mod.SECTIONS if s["famille"] == "qualitatif"),
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    # Ordre venture PUIS entretien (ownership vérifiée avant toute lecture
    # d'Entretiens, cf. revue post-Task 4) — pas l'ordre inverse du brief d'origine.
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": false, "question": "Et après le devis, comment ça se passe ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre",
                          json={"message": "Un client appelle, on qualifie, on envoie un devis."})
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "Et après le devis, comment ça se passe ?"
    assert "qualifie" in row.transcript


async def test_derniere_section_couverte_declenche_la_cloture(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    toutes_sauf_derniere = [s["id"] for s in entretiens_mod.SECTIONS[:-1]]
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante=entretiens_mod.SECTIONS[-1]["id"], sections_couvertes=toutes_sauf_derniere,
        transcript="## communication\n", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    # Même correction d'ordre que ci-dessus (venture PUIS entretien).
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": true, "question": null}'

    async def _fake_cloturer(s, v, row, transcript):
        return "termine", None

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "Par email surtout."})
    body = r.json()
    assert body["statut"] == "termine"
    assert body["question"] is None


async def test_cloturer_pousse_le_transcript_puis_rappelle_auditer(monkeypatch):
    from types import SimpleNamespace
    v = SimpleNamespace(id=VID, audit_id=None)
    row = SimpleNamespace(id="e1")

    calls = []

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            calls.append((url, kw))
            if url.endswith("/ingerer"):
                return SimpleNamespace(status_code=200, json=lambda: {"id": "doc-transcript"})
            if url.endswith("/auditer"):
                return SimpleNamespace(status_code=202, json=lambda: {"id": "audit-new", "statut": "en_cours"})
            raise AssertionError(f"unexpected POST {url}")

        async def get(self, url, **kw):
            calls.append((url, kw))
            return SimpleNamespace(status_code=200, json=lambda: {"documents": [{"id": "doc-transcript"}]})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_URL", "http://ingestion.test")
    monkeypatch.setattr(entretiens_mod.settings, "AUDIT_URL", "http://audit.test")
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_KEY", "k")

    class _FakeSessionCloture:
        async def execute(self, *a, **k):
            return None

    statut, sync_erreur = await entretiens_mod._cloturer(
        _FakeSessionCloture(), v, row, transcript="## commercial\nOn répond au tel.")
    assert statut == "termine"
    assert sync_erreur is None
    assert v.audit_id == "audit-new"
    urls = [c[0] for c in calls]
    assert any(u.endswith("/ingerer") for u in urls)
    assert any(u.endswith("/auditer") for u in urls)


async def test_cloturer_best_effort_si_ingestion_injoignable(monkeypatch):
    from types import SimpleNamespace
    import httpx
    v = SimpleNamespace(id=VID, audit_id=None)
    row = SimpleNamespace(id="e1")

    class _FakeAsyncClientEnPanne:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **kw):
            raise httpx.ConnectError("down")

        async def get(self, url, **kw):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClientEnPanne)
    monkeypatch.setattr(entretiens_mod.settings, "INGESTION_URL", "http://ingestion.test")
    monkeypatch.setattr(entretiens_mod.settings, "AUDIT_URL", "http://audit.test")

    class _FakeSessionCloture:
        async def execute(self, *a, **k):
            return None

    statut, sync_erreur = await entretiens_mod._cloturer(
        _FakeSessionCloture(), v, row, transcript="texte")
    assert statut == "termine"  # ne bloque JAMAIS la clôture
    assert sync_erreur is not None
    assert v.audit_id is None  # pas de rappel /auditer possible sans doc_ids
