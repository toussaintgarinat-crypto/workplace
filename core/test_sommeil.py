"""S243 — briques qui dorment : réveil à la demande, endormissement, garde-fous.

Le module `sommeil` ne parle à Docker que par un « backend » injectable : ici un faux Docker
en mémoire, donc aucun conteneur réel n'est touché.

$ cd core && python3 -m pytest test_sommeil.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402

import sommeil  # noqa: E402


class FauxDocker:
    """Conteneurs en mémoire : {nom: {"running": bool, "sante": "healthy"|"starting"|None}}."""

    def __init__(self, conteneurs):
        self.c = conteneurs
        self.demarres, self.arretes = [], []
        self.demarrage_lent = 0  # nb d'inspections en « starting » après un start

    async def inspecter(self, nom):
        if nom not in self.c:
            return None
        e = self.c[nom]
        if e["running"] and self.demarrage_lent > 0 and e.get("sante") == "starting":
            self.demarrage_lent -= 1
            if self.demarrage_lent == 0:
                e["sante"] = "healthy"
        return dict(e)

    async def demarrer(self, nom):
        self.demarres.append(nom)
        self.c[nom]["running"] = True
        self.c[nom]["sante"] = "starting" if self.demarrage_lent else "healthy"

    async def arreter(self, nom):
        self.arretes.append(nom)
        self.c[nom]["running"] = False
        self.c[nom]["sante"] = None


class Registre:
    def __init__(self, briques):
        self.briques = briques


def _registre():
    return Registre({
        "geo": {"sommeil": {"conteneurs": ["workplace_geo"], "inactivite_min": 30}},
        "video": {"sommeil": {"conteneurs": ["workplace_video", "workplace_video_worker"],
                              "inactivite_min": 10, "attente_s": 5}},
        "calcul": {},                                   # n'a pas opté pour le sommeil
        "gateway": {"sommeil": {"conteneurs": ["gateway-gateway-1"]}},  # protégée en dur
    })


@pytest.fixture(autouse=True)
def _isoler(monkeypatch):
    sommeil._ACTIVITE.clear()
    monkeypatch.setattr(sommeil, "PAS_ATTENTE_S", 0.0)
    monkeypatch.setattr(sommeil, "ACTIF", True)   # le test « inerte » le remet à False
    yield
    sommeil._ACTIVITE.clear()
    sommeil.definir_backend(None)


def _docker(**kw):
    d = FauxDocker({
        "workplace_geo": {"running": False, "sante": None},
        "workplace_video": {"running": True, "sante": "healthy"},
        "workplace_video_worker": {"running": True, "sante": None},
        "gateway-gateway-1": {"running": True, "sante": "healthy"},
    })
    d.c.update(kw)
    sommeil.definir_backend(d)
    return d


def run(coro):
    return asyncio.run(coro)


# ── config / garde-fous ──────────────────────────────────────────────────────

def test_seule_une_brique_qui_a_opte_peut_dormir():
    r = _registre()
    assert sommeil.config(r, "geo")["conteneurs"] == ["workplace_geo"]
    assert sommeil.config(r, "calcul") is None
    assert sommeil.config(r, "inconnue") is None


def test_brique_protegee_jamais_endormissable_meme_si_son_manifeste_le_dit():
    assert sommeil.config(_registre(), "gateway") is None
    for nom in ("core", "gateway", "gateway-sync", "keycloak", "memoire", "agenda", "sommeil-proxy"):
        assert nom in sommeil.NON_ENDORMISSABLES


def test_manifeste_sommeil_mal_forme_est_ignore():
    r = Registre({"x": {"sommeil": {"conteneurs": "workplace_x"}},     # pas une liste
                  "y": {"sommeil": {"conteneurs": []}},                # vide
                  "z": {"sommeil": {"conteneurs": ["ok"], "inactivite_min": "abc"}}})
    assert sommeil.config(r, "x") is None
    assert sommeil.config(r, "y") is None
    assert sommeil.config(r, "z")["inactivite_min"] == sommeil.INACTIVITE_DEFAUT_MIN


# ── état ─────────────────────────────────────────────────────────────────────

def test_etat_endormie_eveillee_demarrage_inconnue():
    _docker()
    r = _registre()
    assert run(sommeil.etat(r, "geo")) == "endormie"
    assert run(sommeil.etat(r, "video")) == "eveillee"
    assert run(sommeil.etat(r, "calcul")) == "inconnue"
    d = _docker()
    d.c["workplace_video"]["sante"] = "starting"
    assert run(sommeil.etat(r, "video")) == "demarrage"


def test_etat_brique_a_plusieurs_conteneurs_est_endormie_si_un_seul_est_arrete():
    d = _docker()
    d.c["workplace_video_worker"]["running"] = False
    assert run(sommeil.etat(_registre(), "video")) == "endormie"


def test_conteneur_introuvable_donne_inconnue_et_pas_endormie():
    # Sinon la santé globale annoncerait « endormie » pour une brique simplement mal nommée.
    _docker()
    r = Registre({"fantome": {"sommeil": {"conteneurs": ["nexistepas"]}}})
    assert run(sommeil.etat(r, "fantome")) == "inconnue"


# ── réveil ───────────────────────────────────────────────────────────────────

def test_reveiller_demarre_et_attend_healthy():
    d = _docker()
    d.demarrage_lent = 3
    res = run(sommeil.reveiller(_registre(), "geo", attente_s=5))
    assert res["ok"] and res["etat"] == "eveillee"
    assert d.demarres == ["workplace_geo"]


def test_reveiller_une_brique_deja_eveillee_ne_touche_a_rien():
    d = _docker()
    res = run(sommeil.reveiller(_registre(), "video"))
    assert res["ok"] and d.demarres == []


def test_reveiller_ne_demarre_que_les_conteneurs_arretes():
    d = _docker()
    d.c["workplace_video_worker"]["running"] = False
    run(sommeil.reveiller(_registre(), "video"))
    assert d.demarres == ["workplace_video_worker"]


def test_reveiller_echoue_proprement_si_jamais_healthy():
    d = _docker()
    d.demarrage_lent = 10_000   # reste « starting » : l'attente doit expirer
    res = run(sommeil.reveiller(_registre(), "geo", attente_s=0.05))
    assert not res["ok"] and "délai" in res["message"].lower()


def test_reveiller_brique_sans_option_sommeil_est_refuse_clairement():
    _docker()
    res = run(sommeil.reveiller(_registre(), "calcul"))
    assert not res["ok"] and "sommeil" in res["message"].lower()


def test_deux_reveils_simultanes_ne_demarrent_qu_une_fois():
    d = _docker()
    d.demarrage_lent = 2

    async def deux():
        return await asyncio.gather(sommeil.reveiller(_registre(), "geo", attente_s=5),
                                    sommeil.reveiller(_registre(), "geo", attente_s=5))
    a, b = run(deux())
    assert a["ok"] and b["ok"] and d.demarres == ["workplace_geo"]


# ── endormissement ───────────────────────────────────────────────────────────

def test_endormir_arrete_tous_les_conteneurs_de_la_brique():
    d = _docker()
    res = run(sommeil.endormir(_registre(), "video"))
    assert res["ok"] and sorted(d.arretes) == ["workplace_video", "workplace_video_worker"]


def test_endormir_refuse_une_brique_protegee_et_ne_touche_a_rien():
    d = _docker()
    res = run(sommeil.endormir(_registre(), "gateway"))
    assert not res["ok"] and d.arretes == []
    res = run(sommeil.endormir(_registre(), "calcul"))
    assert not res["ok"] and d.arretes == []


# ── auto-réveil avant un appel d'outil ───────────────────────────────────────

def test_assurer_eveillee_reveille_une_brique_endormie_et_note_l_activite():
    d = _docker()
    assert run(sommeil.assurer_eveillee(_registre(), "geo")) is None   # None = tout va bien
    assert d.demarres == ["workplace_geo"] and "geo" in sommeil._ACTIVITE


def test_assurer_eveillee_ignore_les_briques_sans_option():
    d = _docker()
    assert run(sommeil.assurer_eveillee(_registre(), "calcul")) is None
    assert run(sommeil.assurer_eveillee(_registre(), "cœur")) is None
    assert d.demarres == []


def test_assurer_eveillee_renvoie_un_message_si_le_reveil_echoue():
    d = _docker()
    d.demarrage_lent = 10_000
    msg = run(sommeil.assurer_eveillee(_registre(), "geo", attente_s=0.05))
    assert msg and "geo" in msg


# ── balayage d'inactivité ────────────────────────────────────────────────────

def test_balayer_endort_les_briques_inactives_depuis_assez_longtemps(monkeypatch):
    d = _docker()
    t0 = 1_000_000.0
    sommeil.noter_activite("video", maintenant=t0)
    dormies = run(sommeil.balayer(_registre(), maintenant=t0 + 11 * 60))   # seuil video = 10 min
    assert dormies == ["video"] and "workplace_video" in d.arretes


def test_balayer_laisse_en_paix_une_brique_recemment_utilisee():
    d = _docker()
    t0 = 1_000_000.0
    sommeil.noter_activite("video", maintenant=t0)
    assert run(sommeil.balayer(_registre(), maintenant=t0 + 5 * 60)) == []
    assert d.arretes == []


def test_balayer_ne_coupe_pas_une_brique_dont_on_ignore_l_activite_au_demarrage():
    # Après un redémarrage du Cœur, on ne sait pas depuis quand elle sert : on part de
    # maintenant (le délai d'inactivité repart de zéro) au lieu de tout éteindre d'un coup.
    d = _docker()
    t0 = 1_000_000.0
    assert run(sommeil.balayer(_registre(), maintenant=t0)) == []
    assert d.arretes == []
    assert run(sommeil.balayer(_registre(), maintenant=t0 + 11 * 60)) == ["video"]


def test_balayer_est_inerte_si_le_sommeil_est_desactive(monkeypatch):
    d = _docker()
    monkeypatch.setattr(sommeil, "ACTIF", False)
    sommeil.noter_activite("video", maintenant=0.0)
    assert run(sommeil.balayer(_registre(), maintenant=10 ** 9)) == []
    assert d.arretes == []
