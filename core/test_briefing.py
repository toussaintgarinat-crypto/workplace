"""Validation du briefing quotidien (Sprint S30).

Autonome : aucune dépendance pytest, aucun vrai réseau ni vrai LLM (httpx et
`llm_pipeline.completer` simulés), journaux SQLite/JSONL isolés en dossier
temporaire.
    $ cd core && python3 test_briefing.py
Sortie « ✅ TOUS LES TESTS PASSENT » = collecte tolérante + synthèse économe +
dépôt en rappel idempotent par jour OK.
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime

# Isole les journaux et fournit le secret requis AVANT les imports du Cœur.
_tmp = tempfile.mkdtemp()
os.environ["RAPPELS_DB"] = os.path.join(_tmp, "rappels.db")
os.environ["USAGE_LLM_PATH"] = os.path.join(_tmp, "usage.jsonl")
os.environ.setdefault("GATEWAY_KEY", "test-cle")
sys.path.insert(0, os.path.dirname(__file__))

import briefing            # noqa: E402
import journal_usage       # noqa: E402
import llm_pipeline        # noqa: E402
import proactif            # noqa: E402

JOUR = datetime(2026, 6, 11, 8, 0, 0)  # un mercredi matin


# ── Doublures ────────────────────────────────────────────────────────────────

class _Registre:
    def __init__(self, briques: dict):
        self.briques = briques


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class _FakeClient:
    """AsyncClient httpx simulé : route les GET Forge selon le chemin demandé."""
    reponses: dict = {}     # chemin → (_FakeResp | Exception)

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None):
        for chemin, rep in _FakeClient.reponses.items():
            if url.endswith(chemin):
                if isinstance(rep, Exception):
                    raise rep
                return rep
        return _FakeResp(404, {})


def _reset():
    proactif.init_db()
    with proactif._conn() as c:
        c.execute("DELETE FROM rappels")
    # Registre minimal : forge résolu par port (cf. orchestrateur._brique_base).
    reg = _Registre({"forge": {"nom": "forge", "port": 5700}})
    # Forge en ligne par défaut : 2 impayés + un pipeline.
    _FakeClient.reponses = {
        "/relances/apercu": _FakeResp(200, {"nb_dues": 2, "montant_total": 1450,
                                            "dues": [{"niveau": "J+7"}, {"niveau": "J+30"}]}),
        "/crm": _FakeResp(200, {"total": 3,
                                "prospects": [{"nom": "X"}, {"nom": "Y"}, {"nom": "Z"}],
                                "pipeline": {"valeur_totale": 9000,
                                             "par_statut": {"prospect": {"nombre": 2, "valeur": 4000}}}}),
    }
    briefing.httpx.AsyncClient = _FakeClient

    async def _agenda_2rdv(registre, debut, fin):
        return [{"start_at": "2026-06-11T09:30:00", "title": "Point client", "location": "Visio"},
                {"start_at": "2026-06-11T14:00:00", "title": "Démo Forge", "location": None}]
    briefing.agenda.lister_evenements = _agenda_2rdv

    # LLM simulé : renvoie un Resultat ok, sans réseau.
    async def _completer_ok(messages, **kw):
        _completer_ok.dernier_kw = kw
        return llm_pipeline.Resultat(message={"content": "Bonjour ! 2 RDV aujourd'hui…"},
                                     modele_utilise="free/eco", cout_usd=0.0)
    _completer_ok.dernier_kw = {}
    briefing.llm_pipeline.completer = _completer_ok

    # Chaîne de modèles sans réseau : un gratuit en tête.
    async def _chaine(conf=None):
        return ["free/eco", "deepseek/deepseek-v4-flash"]
    briefing.config_assistant.chaine_modeles = _chaine

    return reg, _completer_ok


# ── Collecte ─────────────────────────────────────────────────────────────────

def test_collecter_assemble_les_quatre_sources():
    reg, _ = _reset()
    faits = asyncio.run(briefing.collecter(reg, jour=JOUR))
    assert faits["date"] == "2026-06-11"
    assert faits["agenda"]["nombre"] == 2
    assert faits["agenda"]["rendez_vous"][0]["heure"] == "09:30"
    assert faits["impayes"]["nb_dues"] == 2
    # Le pipeline est réduit : récap, pas la liste complète des prospects.
    assert faits["pipeline"]["total_prospects"] == 3
    assert faits["pipeline"]["pipeline"]["valeur_totale"] == 9000
    assert "prospects" not in faits["pipeline"]
    assert faits["cout_llm_veille"]["date"] == "2026-06-10"


def test_collecter_tolere_forge_hors_ligne():
    reg, _ = _reset()
    _FakeClient.reponses = {"/relances/apercu": briefing.httpx.ConnectError("down"),
                            "/crm": briefing.httpx.ConnectError("down")}
    faits = asyncio.run(briefing.collecter(reg, jour=JOUR))
    # L'agenda reste collecté ; Forge devient `indisponible` sans casser le reste.
    assert faits["agenda"]["nombre"] == 2
    assert "indisponible" in faits["impayes"]
    assert "indisponible" in faits["pipeline"]


def test_collecter_tolere_forge_absent_du_registre():
    _, _ = _reset()
    reg_sans_forge = _Registre({"memoire": {"nom": "memoire", "port": 5600}})
    faits = asyncio.run(briefing.collecter(reg_sans_forge, jour=JOUR))
    assert "indisponible" in faits["impayes"]
    assert "indisponible" in faits["pipeline"]


# ── Coût de la veille (journal d'usage) ──────────────────────────────────────

def test_agregat_jour_filtre_par_date():
    _reset()
    # Deux appels la veille, un autre jour à ignorer.
    journal_usage.JOURNAL_PATH.write_text(
        '{"ts":"2026-06-10T09:00:00+00:00","cout_usd":0.01,"tokens_in":100,"tokens_out":50}\n'
        '{"ts":"2026-06-10T18:00:00+00:00","cout_usd":0.02,"tokens_in":200,"tokens_out":80}\n'
        '{"ts":"2026-06-09T10:00:00+00:00","cout_usd":9.99,"tokens_in":1,"tokens_out":1}\n',
        encoding="utf-8")
    agg = journal_usage.agregat_jour("2026-06-10")
    assert agg["appels"] == 2
    assert round(agg["cout_usd"], 4) == 0.03
    assert agg["tokens_in"] == 300


# ── Orchestration : dépôt + idempotence ──────────────────────────────────────

def test_executer_depose_un_rappel_et_est_idempotent():
    reg, completer = _reset()
    r1 = asyncio.run(briefing.executer(reg, jour=JOUR))
    assert r1["statut"] == "cree"
    assert r1["cle"] == "briefing:2026-06-11"
    # L'économe a bien été sollicité avec la bonne étiquette de journal.
    assert completer.dernier_kw["etiquette"] == "briefing"
    # Un rappel de type `briefing` est visible dans la pastille 🔔.
    briefs = [x for x in proactif.lister() if x["type"] == "briefing"]
    assert len(briefs) == 1
    assert briefs[0]["corps"].startswith("Bonjour")

    # 2e passage le même jour : pas de doublon (même lu).
    r2 = asyncio.run(briefing.executer(reg, jour=JOUR))
    assert r2["statut"] == "deja_fait"
    assert len([x for x in proactif.lister() if x["type"] == "briefing"]) == 1


def test_executer_forcer_regenere_sans_dupliquer():
    reg, _ = _reset()
    asyncio.run(briefing.executer(reg, jour=JOUR))
    r = asyncio.run(briefing.executer(reg, jour=JOUR, forcer=True))
    assert r["statut"] == "cree"
    # `forcer` remplace le briefing du jour : un seul reste visible, pas deux.
    assert len([x for x in proactif.lister() if x["type"] == "briefing"]) == 1


def test_executer_signale_un_echec_de_synthese():
    reg, _ = _reset()

    async def _completer_ko(messages, **kw):
        return llm_pipeline.Resultat(erreur="Aucun modèle disponible.")
    briefing.llm_pipeline.completer = _completer_ko

    r = asyncio.run(briefing.executer(reg, jour=JOUR))
    assert r["ok"] is False and r["statut"] == "echec_synthese"
    # Aucun rappel déposé si la synthèse échoue (pas de briefing vide).
    assert [x for x in proactif.lister() if x["type"] == "briefing"] == []


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
