"""S228 : entretien guidé IA."""
from __future__ import annotations

import json
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

    async def _fake_cloturer(v, transcript):
        return "termine", None, None

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

    statut, sync_erreur, audit_id = await entretiens_mod._cloturer(
        v, transcript="## commercial\nOn répond au tel.")
    assert statut == "termine"
    assert sync_erreur is None
    # `audit_id` est RENDU (revue finale S228, Finding I2) : `_cloturer` ne touche plus
    # aucune session, c'est l'appelant qui persiste dans une transaction courte.
    assert audit_id == "audit-new"
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

    statut, sync_erreur, audit_id = await entretiens_mod._cloturer(v, transcript="texte")
    assert statut == "termine"  # ne bloque JAMAIS la clôture
    assert sync_erreur is not None
    assert audit_id is None
    assert v.audit_id is None  # pas de rappel /auditer possible sans doc_ids


async def test_terminer_cloture_explicitement_avant_squelette_complet(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.clients", sections_couvertes=["qualitatif.organisation"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    # Ownership d'abord (v), puis lecture de l'entretien (row) — même ordre que
    # demarrer_entretien/repondre_entretien/etat_entretien, pour cohérence.
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))

    async def _fake_cloturer(v, transcript):
        return "termine", None, None

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    assert r.json()["statut"] == "termine"


async def test_terminer_404_si_aucun_entretien(client, app, monkeypatch):
    """Venture possédée mais aucune ligne Entretiens (squelette jamais démarré, ou
    table vide) : doit 404 sur la branche `row is None`, pas sur la branche
    ownership. rows_by_call a deux entrées distinctes (venture réelle possédée,
    puis Entretiens réellement vide) — pas un unique `[[]]` qui, via le repli
    `pop(0) if self._rows_by_call else []` de `_FakeSession.execute`, renverrait
    aussi [] pour n'importe quel appel ultérieur et masquerait un retrait du
    guard d'ownership (cf. test_terminer_404_si_venture_pas_a_soi ci-dessous,
    qui couvre spécifiquement cette autre branche)."""
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    sess_holder = []

    def _make_session():
        sess = _FakeSession(rows_by_call=[[v], []])
        sess_holder.append(sess)
        return sess

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make_session)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 404
    # Les deux requêtes en file ont bien été consommées (venture puis entretien) :
    # preuve que le 404 vient de « aucun entretien », pas d'un court-circuit ownership.
    assert sess_holder[0].execute_count == 2


async def test_terminer_404_si_venture_pas_a_soi(client, app, monkeypatch):
    """Sécurité : sans le filtre owner_id (et sans le garde `v is not None` qui
    court-circuite la lecture d'Entretiens), n'importe quel utilisateur authentifié
    pourrait lire/clôturer l'entretien de n'importe quelle venture en devinant son
    id. rows_by_call met en file un VRAI entretien en 2e position : si le garde
    d'ownership disparaissait, cette ligne serait consommée et ses données
    fuiteraient dans la réponse — ce test irait au rouge. Avec le garde intact,
    la requête Entretiens n'est jamais exécutée (execute_count == 1) et la ligne
    en file reste non consommée."""
    app.dependency_overrides[get_current_user] = _fake_user
    entretien_qui_fuirait = SimpleNamespace(
        id="99999999-9999-9999-9999-999999999999", venture_id=VID,
        section_courante="qualitatif.problemes_connus", sections_couvertes=["qualitatif.organisation"],
        transcript="## secret\nDonnée confidentielle d'une autre venture.", statut="en_cours",
        sync_erreur=None, derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    sess_holder = []

    def _make_session():
        sess = _FakeSession(rows_by_call=[[], [entretien_qui_fuirait]])
        sess_holder.append(sess)
        return sess

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make_session)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 404
    body_text = r.text
    assert "qualitatif.problemes_connus" not in body_text
    assert "99999999-9999-9999-9999-999999999999" not in body_text
    assert "Donnée confidentielle" not in body_text
    # Une seule requête exécutée (Ventures) — Entretiens jamais interrogé, donc la
    # ligne en file (qui aurait fait fuiter des données d'une autre venture) n'a
    # jamais été consommée.
    assert sess_holder[0].execute_count == 1


async def test_etat_renvoie_l_entretien_courant(client, app, monkeypatch):
    from types import SimpleNamespace
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    row = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.clients", sections_couvertes=["qualitatif.organisation"],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], [row]]))
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 200
    assert r.json()["sectionCourante"] == "qualitatif.clients"


async def test_etat_404_si_aucun_entretien(client, app, monkeypatch):
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture()
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[v], []]))
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 404


async def test_etat_404_si_venture_pas_a_soi(client, app, monkeypatch):
    """Sécurité : sans le filtre owner_id (et sans le garde `v is not None` qui
    court-circuite la lecture d'Entretiens), n'importe quel utilisateur authentifié
    pourrait lire l'état d'entretien de n'importe quelle venture en devinant son id
    (même classe de bug que les fixes Critical S227 sur les scopes client_lecture).

    rows_by_call=[[], [row]] met en file un VRAI entretien en 2e position. Avec un
    unique `[[]]` (ancienne version), `_FakeSession.execute` retombe sur `[]` pour
    TOUT appel au-delà de la file (`pop(0) if self._rows_by_call else []`) — donc
    même une régression qui supprimerait le garde `v is not None` et interrogerait
    Entretiens sans condition obtiendrait quand même [] et 404-erait, mais pour la
    MAUVAISE raison (repli de la fausse session, pas le garde d'ownership). En
    mettant un vrai `row` en 2e position, si le garde disparaît, cette ligne serait
    consommée et ses données fuiteraient dans le corps de la réponse — ce test irait
    au rouge dans ce cas, ce que l'ancienne version ne pouvait pas détecter."""
    app.dependency_overrides[get_current_user] = _fake_user
    entretien_qui_fuirait = SimpleNamespace(
        id="88888888-8888-8888-8888-888888888888", venture_id=VID,
        section_courante="qualitatif.contraintes", sections_couvertes=["qualitatif.organisation"],
        transcript="## secret\nDonnée confidentielle d'une autre venture.", statut="en_cours",
        sync_erreur=None, derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    sess_holder = []

    def _make_session():
        sess = _FakeSession(rows_by_call=[[], [entretien_qui_fuirait]])
        sess_holder.append(sess)
        return sess

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make_session)
    r = await client.get(f"/api/ventures/{VID}/entretien/etat")
    assert r.status_code == 404
    body_text = r.text
    assert "qualitatif.contraintes" not in body_text
    assert "88888888-8888-8888-8888-888888888888" not in body_text
    assert "Donnée confidentielle" not in body_text
    # Une seule requête exécutée (Ventures) — Entretiens jamais interrogé, donc la
    # ligne en file (qui aurait fait fuiter des données d'une autre venture) n'a
    # jamais été consommée.
    assert sess_holder[0].execute_count == 1


# ── Revue finale S228 : C2 (datetimes naïfs), I2 (sessions), I3 (idempotence),
#    I4 (syncErreur exposé), I5 (order_by manquant) ────────────────────────────────

class _SessionEspionne(_FakeSession):
    """`_FakeSession` + traçabilité : garde les statements exécutés et le nombre de
    sessions ouvertes à un instant donné (partagé entre toutes les instances via
    `compteur`), pour prouver qu'aucun appel réseau ne tourne session ouverte."""

    def __init__(self, rows_by_call, journal, compteur):
        super().__init__(rows_by_call)
        self.journal = journal
        self._compteur = compteur

    async def __aenter__(self):
        self._compteur["ouvertes"] += 1
        self._compteur["max"] = max(self._compteur["max"], self._compteur["ouvertes"])
        return self

    async def __aexit__(self, *a):
        self._compteur["ouvertes"] -= 1
        return False

    async def execute(self, stmt=None, *a, **k):
        self.journal.append(stmt)
        return await super().execute(stmt, *a, **k)


def _espion(monkeypatch, rows_by_call):
    """Installe un `SessionLocal` espionné. Rend (journal_des_statements, compteur)."""
    journal, compteur = [], {"ouvertes": 0, "max": 0}
    monkeypatch.setattr(
        entretiens_mod, "SessionLocal",
        lambda: _SessionEspionne(list(rows_by_call), journal, compteur))
    return journal, compteur


def _datetimes_ecrits(journal):
    """Tous les datetimes présents dans les paramètres liés des statements exécutés."""
    vus = []
    for stmt in journal:
        try:
            params = stmt.compile().params
        except Exception:  # SELECT sans param datetime, ou statement non compilable
            continue
        vus.extend(v for v in params.values() if isinstance(v, datetime))
    return vus


def _row_en_cours(**kw):
    from types import SimpleNamespace
    base = dict(
        id="33333333-3333-3333-3333-333333333333", venture_id=VID,
        section_courante="qualitatif.organisation", sections_couvertes=[],
        transcript="", statut="en_cours", sync_erreur=None,
        derniere_activite=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_demarrer_persiste_des_datetimes_naifs(client, app, monkeypatch):
    """Finding C2 : `Entretiens.derniere_activite`/`created_at` sont des colonnes
    `timestamp without time zone`. asyncpg refuse d'y encoder un datetime AWARE
    (« can't subtract offset-naive and offset-aware datetimes », remonté en DataError) —
    la toute première utilisation réelle aurait planté. Aucun test ne pouvait le voir :
    le filet Forge n'a pas de vraie DB, d'où cette assertion structurelle."""
    app.dependency_overrides[get_current_user] = _fake_user
    sessions = []

    def _make():
        sess = _FakeSession(rows_by_call=[[_mk_venture()], []])
        sessions.append(sess)
        return sess

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make)
    r = await client.post(f"/api/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    ajoute = sessions[0].added[0]
    assert ajoute.derniere_activite.tzinfo is None, "datetime aware → DataError asyncpg"
    assert ajoute.created_at.tzinfo is None, "datetime aware → DataError asyncpg"


async def test_repondre_persiste_des_datetimes_naifs(client, app, monkeypatch):
    """Même garde C2 sur les `update(...)` de `repondre_entretien` (Entretiens ET
    Ventures.updated_at, toutes deux naïves)."""
    app.dependency_overrides[get_current_user] = _fake_user
    journal, _ = _espion(monkeypatch, [[_mk_venture(profil_entreprise=None)], [_row_en_cours()]])

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["SARL"]}'
        return '{"couverte": false, "question": "Et encore ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "SARL"})
    assert r.status_code == 200
    ecrits = _datetimes_ecrits(journal)
    assert ecrits, "aucun datetime persisté — le test ne prouve plus rien"
    assert all(d.tzinfo is None for d in ecrits), ecrits


async def test_terminer_persiste_des_datetimes_naifs(client, app, monkeypatch):
    """Même garde C2 sur `terminer_entretien`."""
    app.dependency_overrides[get_current_user] = _fake_user
    journal, _ = _espion(monkeypatch, [[_mk_venture()], [_row_en_cours()]])

    async def _fake_cloturer(v, transcript):
        return "termine", None, "audit-1"

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    ecrits = _datetimes_ecrits(journal)
    assert ecrits, "aucun datetime persisté — le test ne prouve plus rien"
    assert all(d.tzinfo is None for d in ecrits), ecrits


async def test_repondre_ne_tient_aucune_session_pendant_la_cloture(client, app, monkeypatch):
    """Finding I2 : `_cloturer` enchaîne 3 appels HTTP à 30 s de timeout (~90 s au pire).
    Les exécuter dans le `async with SessionLocal()` de lecture immobilisait une
    connexion et une transaction ouvertes tout ce temps. Motif tranché en S227
    (`ventures.get_venture_dossier` ferme sa session AVANT son fan-out HTTP)."""
    app.dependency_overrides[get_current_user] = _fake_user
    derniere = entretiens_mod.SECTIONS[-1]["id"]
    row = _row_en_cours(section_courante=derniere,
                        sections_couvertes=[s["id"] for s in entretiens_mod.SECTIONS[:-1]],
                        transcript="## communication\n")
    _, compteur = _espion(monkeypatch, [[_mk_venture()], [row]])
    vu = {}

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": true, "question": null}'

    async def _fake_cloturer(v, transcript):
        vu["sessions_ouvertes"] = compteur["ouvertes"]
        return "termine", None, "audit-1"

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "Par email."})
    assert r.status_code == 200
    assert r.json()["statut"] == "termine"
    assert vu["sessions_ouvertes"] == 0, "connexion DB immobilisée pendant ~90 s d'appels HTTP"
    assert compteur["max"] == 1, "sessions imbriquées — deux connexions pour un seul tour"


async def test_terminer_ne_tient_aucune_session_pendant_la_cloture(client, app, monkeypatch):
    """Même garde I2 côté `terminer_entretien`."""
    app.dependency_overrides[get_current_user] = _fake_user
    _, compteur = _espion(monkeypatch, [[_mk_venture()], [_row_en_cours()]])
    vu = {}

    async def _fake_cloturer(v, transcript):
        vu["sessions_ouvertes"] = compteur["ouvertes"]
        return "termine", None, None

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    assert vu["sessions_ouvertes"] == 0, "connexion DB immobilisée pendant ~90 s d'appels HTTP"
    assert compteur["max"] == 1


async def test_terminer_deux_fois_ne_rejoue_pas_la_cloture(client, app, monkeypatch):
    """Finding I3 : sans court-circuit, rappeler /terminer sur un entretien déjà clôturé
    proprement rejouait `_cloturer` EN ENTIER — un 2e transcript poussé vers l'ingestion
    (doublon dans le RAG) et un NOUVEL audit qui écrasait `Ventures.audit_id`. Le retry
    n'a de sens que si la clôture précédente avait échoué (`sync_erreur` non nul)."""
    app.dependency_overrides[get_current_user] = _fake_user
    deja = _row_en_cours(statut="termine", sync_erreur=None,
                         sections_couvertes=["qualitatif.organisation"],
                         transcript="## commercial\nDéjà poussé.")
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[_mk_venture()], [deja]]))
    appels = []

    async def _fake_cloturer(v, transcript):
        appels.append(transcript)
        return "termine", None, "audit-2"

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    assert appels == [], "clôture rejouée : 2e push ingestion + audit_id écrasé"
    body = r.json()
    assert body["statut"] == "termine"
    assert body["syncErreur"] is None


async def test_terminer_rejoue_la_cloture_si_la_synchro_avait_echoue(client, app, monkeypatch):
    """Contrepartie du court-circuit I3 : le retry documenté doit rester possible.
    `sync_erreur` non nul = clôture incomplète = `_cloturer` rejoué."""
    app.dependency_overrides[get_current_user] = _fake_user
    ratee = _row_en_cours(statut="termine", sync_erreur="push ingestion échoué (502)",
                          transcript="## commercial\nÀ repousser.")
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[_mk_venture()], [ratee]]))
    appels = []

    async def _fake_cloturer(v, transcript):
        appels.append(transcript)
        return "termine", None, "audit-2"

    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)
    r = await client.post(f"/api/ventures/{VID}/entretien/terminer")
    assert r.status_code == 200
    assert appels == ["## commercial\nÀ repousser."]
    assert r.json()["syncErreur"] is None


async def test_repondre_expose_sync_erreur(client, app, monkeypatch):
    """Finding I4 : la clôture est best-effort — `statut` vaut "termine" même si le push
    d'ingestion ou le rappel /auditer a échoué. Sans `syncErreur` dans le corps, le Cœur
    annonçait « l'analyse est relancée » y compris dans ce cas."""
    app.dependency_overrides[get_current_user] = _fake_user
    derniere = entretiens_mod.SECTIONS[-1]["id"]
    row = _row_en_cours(section_courante=derniere,
                        sections_couvertes=[s["id"] for s in entretiens_mod.SECTIONS[:-1]],
                        transcript="## communication\n")
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[_mk_venture()], [row]]))

    async def _fake_generate(prompt, system=None, **kw):
        return '{"couverte": true, "question": null}'

    async def _fake_cloturer(v, transcript):
        return "termine", "push ingestion échoué (502)", None

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    monkeypatch.setattr(entretiens_mod, "_cloturer", _fake_cloturer)

    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "Par email."})
    assert r.status_code == 200
    body = r.json()
    assert body["statut"] == "termine"
    assert body["syncErreur"] == "push ingestion échoué (502)"


async def test_repondre_expose_sync_erreur_nulle_en_marche_normale(client, app, monkeypatch):
    """Non-régression du chemin nominal : `syncErreur` doit être présent ET nul quand
    tout va bien (sinon le Cœur alarmerait à chaque tour)."""
    app.dependency_overrides[get_current_user] = _fake_user
    monkeypatch.setattr(entretiens_mod, "SessionLocal",
                        lambda: _FakeSession(rows_by_call=[[_mk_venture()], [_row_en_cours()]]))

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["SARL"]}'
        return '{"couverte": false, "question": "Et encore ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "SARL"})
    assert r.json()["syncErreur"] is None


async def test_repondre_selectionne_l_entretien_le_plus_recent(client, app, monkeypatch):
    """Finding I5 : ce SELECT était le seul des 4 de ce fichier sans
    `.order_by(desc(derniere_activite))`. Si deux lignes `en_cours` coexistent pour une
    venture, Postgres en choisit une arbitrairement — `demarrer` pourrait reprendre
    l'une et `repondre` écrire dans l'autre. Même classe de bug que le fix 7ed26b8,
    appliqué au 4e site oublié."""
    app.dependency_overrides[get_current_user] = _fake_user
    journal, _ = _espion(monkeypatch, [[_mk_venture()], [_row_en_cours()]])

    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return '{"valeurs": ["SARL"]}'
        return '{"couverte": false, "question": "Et encore ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    r = await client.post(f"/api/ventures/{VID}/entretien/repondre", json={"message": "SARL"})
    assert r.status_code == 200
    selects = [str(st) for st in journal if str(st).lstrip().upper().startswith("SELECT")]
    entretien_select = [s for s in selects if "entretiens" in s]
    assert entretien_select, selects
    assert "ORDER BY entretiens.derniere_activite DESC" in entretien_select[0], entretien_select[0]


def test_les_quatre_selects_d_entretien_sont_ordonnes():
    """Garde-fou statique contre la réapparition du 5e site oublié : toute lecture
    `select(Entretiens)` de ce router doit être suivie d'un `order_by`."""
    import inspect
    import re as _re

    src = inspect.getsource(entretiens_mod)
    selects = _re.findall(r"select\(Entretiens\)(.{0,1500}?)\.limit\(", src, _re.S)
    assert len(selects) == 4, f"{len(selects)} select(Entretiens) trouvés, 4 attendus"
    for i, suite in enumerate(selects):
        assert "order_by" in suite, f"select(Entretiens) #{i + 1} sans order_by"


# ── Revue finale S228, Finding N1 : fusion du profil contre une lecture FRAÎCHE ──────

def _sessions_en_file(monkeypatch, files):
    """`SessionLocal` qui rend une session DIFFÉRENTE par appel (une par élément de
    `files`), toutes tracées dans le même journal. Indispensable ici : la session de
    LECTURE et la transaction d'ÉCRITURE doivent voir des états de la base différents,
    c'est justement la fenêtre de concurrence qu'on teste."""
    journal, compteur = [], {"ouvertes": 0, "max": 0}
    file_restante = list(files)

    def _make():
        rows = file_restante.pop(0) if file_restante else []
        return _SessionEspionne(list(rows), journal, compteur)

    monkeypatch.setattr(entretiens_mod, "SessionLocal", _make)
    return journal


def _profils_ecrits(journal):
    """Valeurs de `profil_entreprise` réellement passées à un UPDATE."""
    vus = []
    for stmt in journal:
        try:
            params = stmt.compile().params
        except Exception:  # noqa: BLE001
            continue
        if "profil_entreprise" in params and str(stmt).lstrip().upper().startswith("UPDATE"):
            vus.append(params["profil_entreprise"])
    return vus


async def _repondre_avec_extraction(client, monkeypatch, valeurs_extraites):
    async def _fake_generate(prompt, system=None, **kw):
        if "valeurs" in prompt:
            return json.dumps({"valeurs": valeurs_extraites})
        return '{"couverte": false, "question": "Et encore ?"}'

    monkeypatch.setattr(entretiens_mod, "generate_text", _fake_generate)
    return await client.post(f"/api/ventures/{VID}/entretien/repondre",
                             json={"message": "On est à Lyon"})


async def test_repondre_ne_perd_pas_une_ecriture_concurrente_du_profil(client, app, monkeypatch):
    """Finding N1 : depuis le fix I2 (sessions courtes), le profil est lu au début de la
    requête puis écrit APRÈS deux allers-retours LLM. Fusionner contre la valeur périmée
    écrasait en silence toute écriture concurrente de cette fenêtre — typiquement un
    `PATCH /ventures/{id}`, qui remplace `profil_entreprise` EN BLOC (S227). La contrainte
    globale du sprint est explicite : « JAMAIS d'écrasement ».

    Ici, un tiers ajoute la catégorie `clients` pendant les appels LLM. Le profil écrit
    doit contenir LES DEUX : la catégorie concurrente ET l'extraction de ce tour."""
    app.dependency_overrides[get_current_user] = _fake_user
    initial = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    # État de la base au moment de l'ÉCRITURE : quelqu'un a écrit entre-temps.
    concurrent = _mk_venture(profil_entreprise={"organisation": ["SARL"],
                                                "clients": ["PME locales"]})
    journal = _sessions_en_file(monkeypatch, [
        [[initial], [_row_en_cours()]],   # session de lecture
        [[concurrent]],                   # transaction d'écriture : relecture fraîche
    ])

    r = await _repondre_avec_extraction(client, monkeypatch, ["Basée à Lyon"])
    assert r.status_code == 200
    ecrits = _profils_ecrits(journal)
    assert ecrits, "aucun profil écrit — le test ne prouve plus rien"
    assert ecrits[-1] == {"organisation": ["SARL", "Basée à Lyon"],
                          "clients": ["PME locales"]}, ecrits[-1]


async def test_repondre_relit_le_profil_avec_un_verrou_de_ligne(client, app, monkeypatch):
    """La relecture doit VERROUILLER la ligne (`SELECT … FOR UPDATE`), sinon deux tours
    concurrents relisent la même valeur fraîche et le dernier écrase quand même l'autre.
    SQLite ignore la clause ; Postgres (la vraie cible) sérialise."""
    app.dependency_overrides[get_current_user] = _fake_user
    journal = _sessions_en_file(monkeypatch, [
        [[_mk_venture(profil_entreprise=None)], [_row_en_cours()]],
        [[_mk_venture(profil_entreprise=None)]],
    ])
    r = await _repondre_avec_extraction(client, monkeypatch, ["SARL"])
    assert r.status_code == 200
    selects_ventures = [str(st) for st in journal
                        if str(st).lstrip().upper().startswith("SELECT") and "ventures" in str(st)]
    assert len(selects_ventures) == 2, selects_ventures  # ownership + relecture fraîche
    assert "FOR UPDATE" in selects_ventures[-1], selects_ventures[-1]


async def test_repondre_sans_concurrence_fusionne_comme_avant(client, app, monkeypatch):
    """Non-régression : sans écriture concurrente, le profil écrit est exactement celui
    d'avant le fix (la relecture ne doit pas perdre l'état initial)."""
    app.dependency_overrides[get_current_user] = _fake_user
    v = _mk_venture(profil_entreprise={"organisation": ["SARL"]})
    journal = _sessions_en_file(monkeypatch, [[[v], [_row_en_cours()]], [[v]]])
    r = await _repondre_avec_extraction(client, monkeypatch, ["Basée à Lyon"])
    assert r.status_code == 200
    assert _profils_ecrits(journal)[-1] == {"organisation": ["SARL", "Basée à Lyon"]}


async def test_repondre_ne_reecrit_pas_le_profil_sans_extraction(client, app, monkeypatch):
    """Extraction vide : aucune écriture de `profil_entreprise` (donc aucune relecture,
    aucun verrou pris pour rien) — un UPDATE à vide écraserait une écriture concurrente
    par un profil identique à une lecture périmée."""
    app.dependency_overrides[get_current_user] = _fake_user
    journal = _sessions_en_file(monkeypatch, [
        [[_mk_venture(profil_entreprise={"organisation": ["SARL"]})], [_row_en_cours()]],
        [[]],
    ])
    r = await _repondre_avec_extraction(client, monkeypatch, [])
    assert r.status_code == 200
    assert _profils_ecrits(journal) == []
