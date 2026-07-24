"""Routeur d'outils dynamique — le système nerveux découvert (Sprint S64).

Vérifie que les capacités déclarées dans les manifests (S63) deviennent de vrais
outils du LLM, routés SANS dispatch en dur, avec les garde-fous : un nom déjà câblé
en dur prime (zéro régression), les actions sont gardées par confirmation, la liste
blanche et le kill-switch bornent ce que le LLM voit, et un outil inconnu reste inconnu.

Autonome (asyncio.run, faux client httpx, faux registre) — motif du reste de core/.
    $ cd core && python3 test_outils_dynamiques.py
"""
import asyncio
import json
import os

import httpx

import outils  # noqa: E402


class _Registre:
    def __init__(self, briques):
        self.briques = briques


def _registre():
    # calcul expose 2 capacités neuves ; memoire en redéclare une DÉJÀ câblée en dur.
    return _Registre({
        "calcul": {"nom": "calcul", "port": 5990, "capacites": [
            {"nom": "calcul_lister_noeuds", "description": "liste", "methode": "GET",
             "chemin": "/noeuds", "params": {}, "action": False},
            {"nom": "calcul_etat_muscle", "description": "élit", "methode": "GET",
             "chemin": "/muscle",
             "params": {"reveiller": {"type": "boolean"}}, "action": True},
        ]},
        "memoire": {"nom": "memoire", "port": 5600, "capacites": [
            {"nom": "memoire_rappeler", "description": "doublon du statique",
             "methode": "GET", "chemin": "/rappeler", "action": False},
        ]},
    })


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = ""

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp=None, boom=False):
        self.resp = resp or _Resp()
        self.boom = boom
        self.dernier = {}

    async def request(self, methode, url, json=None, params=None, headers=None, timeout=None):
        self.dernier = {"methode": methode, "url": url, "json": json,
                        "params": params, "headers": headers}
        if self.boom:
            raise httpx.ConnectError("injoignable")
        return self.resp


# ── Découverte & specs ────────────────────────────────────────────────────────

def test_capacites_neuves_exposees_sans_les_doublons_statiques():
    dyn = outils._capacites_dynamiques(_registre())
    assert "calcul_lister_noeuds" in dyn and "calcul_etat_muscle" in dyn
    # memoire_rappeler n'est plus en dur (S134 migration) → découvert depuis le manifest.
    assert "memoire_rappeler" in dyn


def test_outils_pour_fusionne_statiques_et_dynamiques():
    base = {o["function"]["name"] for o in outils.OUTILS}
    fusion = {o["function"]["name"] for o in outils.outils_pour(_registre())}
    assert base <= fusion                                    # rien perdu
    assert {"calcul_lister_noeuds", "calcul_etat_muscle", "memoire_rappeler"} <= fusion
    assert len(fusion) >= len(base) + 3  # calcul(2) + memoire(1) au minimum


def test_spec_action_ajoute_confirme_et_marque_requis():
    spec = outils._spec_depuis_capacite({
        "nom": "x", "description": "d", "methode": "POST", "chemin": "/x",
        "params": {"a": {"type": "string", "requis": True}, "b": {"type": "integer"}},
        "action": True})
    p = spec["function"]["parameters"]
    assert p["required"] == ["a"]
    assert "requis" not in p["properties"]["a"]               # nettoyé du schéma
    assert "confirme" in p["properties"]                      # gate exposé au modèle


def test_est_action_distingue_lecture_et_action():
    reg = _registre()
    assert outils.est_action("calcul_etat_muscle", reg) is True
    assert outils.est_action("calcul_lister_noeuds", reg) is False
    # memoire_retenir est maintenant dynamique (S134) : pas dans OUTILS_ACTION, mais
    # est_action le retrouve via les capacités dynamiques si le registre le déclare.
    assert outils.est_action("memoire_retenir", reg) is False  # pas dans ce registre


def test_noms_socle_inclut_statiques_et_socle_manifest():
    # Registre avec une capacité marquée socle:true
    reg_socle = _Registre({
        "memoire": {"nom": "memoire", "port": 5600, "capacites": [
            {"nom": "memoire_rappeler", "description": "rappel", "methode": "GET",
             "chemin": "/rappeler", "action": False, "socle": True},
        ]},
    })
    socle = outils.noms_socle(reg_socle)
    assert outils._NOMS_STATIQUES <= socle                 # tous les statiques dedans
    assert "memoire_rappeler" in socle                     # socle:true du manifest inclus

    # Sans registre → uniquement les statiques
    assert outils.noms_socle() == outils._NOMS_STATIQUES


# ── Routage HTTP ────────────────────────────────────────────────────────────

def test_get_dynamique_route_vers_la_bonne_url():
    cli = _Client(_Resp(200, {"noeuds": []}))
    cap = outils._capacites_dynamiques(_registre())["calcul_lister_noeuds"]
    out = asyncio.run(outils._appel_dynamique(cli, cap, {}))
    assert cli.dernier["methode"] == "GET"
    assert cli.dernier["url"] == "http://host.docker.internal:5990/noeuds"
    assert json.loads(out) == {"noeuds": []}


def test_action_dynamique_gardee_sans_confirme():
    cli = _Client(_Resp(200, {"disponible": True}))
    cap = outils._capacites_dynamiques(_registre())["calcul_etat_muscle"]
    out = json.loads(asyncio.run(outils._appel_dynamique(cli, cap, {"reveiller": True})))
    assert out["confirmation_requise"] is True
    assert cli.dernier == {}                                  # AUCUN appel réseau émis


def test_action_dynamique_executee_avec_confirme():
    cli = _Client(_Resp(200, {"disponible": True}))
    cap = outils._capacites_dynamiques(_registre())["calcul_etat_muscle"]
    out = asyncio.run(outils._appel_dynamique(cli, cap, {"reveiller": True, "confirme": True}))
    assert cli.dernier["methode"] == "GET"
    assert cli.dernier["params"] == {"reveiller": True}        # confirme retiré de la charge
    assert json.loads(out)["disponible"] is True


def test_cle_de_service_envoyee_en_entete():
    os.environ["CALCUL_KEY"] = "secret"
    try:
        cli = _Client(_Resp(200, {"ok": True}))
        cap = outils._capacites_dynamiques(_registre())["calcul_lister_noeuds"]
        asyncio.run(outils._appel_dynamique(cli, cap, {}))
        # Clé de service (X-API-Key) + identité de l'appelant (X-Compte-Id, S167).
        assert cli.dernier["headers"]["X-API-Key"] == "secret"
        assert cli.dernier["headers"]["X-Compte-Id"] == "admin"
    finally:
        os.environ.pop("CALCUL_KEY", None)


def test_identite_appelant_toujours_envoyee_sans_cle():
    """Même sans {BRIQUE}_KEY, le Cœur transmet l'identité de l'appelant (X-Compte-Id) :
    la brique peut décider du périmètre par rôle sans exiger de clé (S167)."""
    os.environ.pop("CALCUL_KEY", None)
    cli = _Client(_Resp(200, {"ok": True}))
    cap = outils._capacites_dynamiques(_registre())["calcul_lister_noeuds"]
    asyncio.run(outils._appel_dynamique(cli, cap, {}))
    assert cli.dernier["headers"] == {"X-Compte-Id": "admin"}


def test_refus_brique_message_honnete():
    cli = _Client(_Resp(503, {}))
    cap = outils._capacites_dynamiques(_registre())["calcul_lister_noeuds"]
    out = json.loads(asyncio.run(outils._appel_dynamique(cli, cap, {})))
    assert out["ok"] is False and "refusé" in out["message"].lower()


def test_url_media_reecrite_pour_le_navigateur_et_le_pont_reseau():
    """images/video/export rapatrient leur production sous `/fichiers/{nom}`, relatif à leur
    PROPRE port interne. Le Cœur doit réécrire `url` en un chemin résolvable par le
    navigateur (`/brique-fichiers/…`) ET fournir `url_interne` (URL absolue mais interne au
    réseau Docker) pour un appelant serveur-à-serveur sans session (le pont Telegram, S196)."""
    reg = _Registre({"images": {"nom": "images", "port": 5950, "capacites": [
        {"nom": "image_generer", "description": "texte→image", "methode": "POST",
         "chemin": "/generer", "params": {"prompt": {"type": "string"}}, "action": True},
    ]}})
    cli = _Client(_Resp(200, {"url": "/fichiers/img-abc.png", "backend": "gateway"}))
    cap = outils._capacites_dynamiques(reg)["image_generer"]
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, cap, {"prompt": "un chat", "confirme": True})))
    assert out["url"] == "/brique-fichiers/images/img-abc.png"
    assert out["url_interne"] == "http://host.docker.internal:5950/fichiers/img-abc.png"


def test_succes_204_sans_corps_renvoie_ok_explicite():
    """Une réponse 2xx sans corps JSON (204 No Content des suppressions REST) ne doit PAS
    renvoyer une chaîne vide à l'assistant, mais un succès honnête et lisible (S167 T5)."""
    class _Resp204:
        status_code = 204
        text = ""

        def json(self):
            raise ValueError("No content")

    cli = _Client(_Resp204())
    cap = outils._capacites_dynamiques(_registre())["calcul_etat_muscle"]  # action:true
    out = json.loads(asyncio.run(outils._appel_dynamique(cli, cap, {"confirme": True})))
    assert out["ok"] is True and out["status"] == 204 and out["brique"] == "calcul"


# ── Garde-fous du plan de contrôle ────────────────────────────────────────────

def test_kill_switch_eteint_les_dynamiques():
    reg = _registre()
    outils.CAPACITES_DYNAMIQUES = False
    try:
        assert outils._capacites_dynamiques(reg) == {}
        noms = {o["function"]["name"] for o in outils.outils_pour(reg)}
        assert "calcul_lister_noeuds" not in noms             # repli honnête : statiques seuls
    finally:
        outils.CAPACITES_DYNAMIQUES = True


def test_liste_blanche_borne_ce_que_voit_le_llm():
    reg = _registre()
    outils._ALLOWLIST = {"calcul_lister_noeuds"}
    try:
        dyn = outils._capacites_dynamiques(reg)
        assert set(dyn) == {"calcul_lister_noeuds"}           # l'autre est masqué
    finally:
        outils._ALLOWLIST = set()


def test_executer_outil_inconnu_reste_inconnu():
    out = asyncio.run(outils.executer("nexiste_pas", {}, _registre()))
    assert "inconnu" in out.lower()


# ── Capacités async (S179) — 202 + polling ──────────────────────────────────

class _ClientAsync:
    """Client stub qui répond :
       - sur POST /resumer -> 202 {job_id, statut:'en_cours'}
       - sur GET /jobs/{id} -> enfile les réponses préchargées dans self.polls.
    """
    def __init__(self, post_resp, polls):
        self.post_resp = post_resp
        self.polls = list(polls)
        self.poll_calls = 0
        self.dernier = {}

    async def request(self, methode, url, json=None, params=None, headers=None, timeout=None):
        self.dernier = {"methode": methode, "url": url}
        if methode == "POST":
            return self.post_resp
        # GET
        self.poll_calls += 1
        return self.polls[min(self.poll_calls - 1, len(self.polls) - 1)]


def _cap_async():
    return {
        "nom": "video_resumer", "brique": "synopsis", "description": "resumer",
        "methode": "POST", "chemin": "/resumer",
        "url": "http://host.docker.internal:6090/resumer",
        "params": {"url": {"type": "string", "requis": True}},
        "action": False, "async": True, "poll_chemin": "/jobs/{id}",
    }


def _patch_client_async(monkeypatch, post_resp, polls):
    """Force _appel_dynamique à utiliser un AsyncClient qui route vers _ClientAsync."""
    import outils_communs
    cli = _ClientAsync(post_resp, polls)

    class _Fab:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return cli

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(outils_communs.httpx, "AsyncClient", lambda *a, **kw: _Fab(*a, **kw))
    return cli


def test_appel_dynamique_async_termine_rend_resultat(monkeypatch):
    post = _Resp(202, {"job_id": "abc", "statut": "en_cours", "poll_url": "/jobs/abc"})
    polls = [
        _Resp(200, {"statut": "en_cours", "progress_pct": 50}),
        _Resp(200, {"statut": "termine", "progress_pct": 100,
                    "resultat": {"titre": "T", "resume": "R"}}),
    ]
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=abc"})))
    assert out["titre"] == "T"
    assert out["resume"] == "R"


def test_appel_dynamique_async_erreur_rend_ok_false_avec_message(monkeypatch):
    post = _Resp(202, {"job_id": "x1", "statut": "en_cours"})
    polls = [_Resp(200, {"statut": "erreur", "erreur": "Vidéo inaccessible"})]
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=bad"})))
    assert out["ok"] is False
    assert "Vidéo inaccessible" in out["message"]


def test_appel_dynamique_async_timeout_rend_message_avec_job_id(monkeypatch):
    import outils_communs
    monkeypatch.setenv("OUTILS_ASYNC_TIMEOUT", "0.05")
    post = _Resp(202, {"job_id": "abc", "statut": "en_cours"})
    polls = [_Resp(200, {"statut": "en_cours"})]  # toujours en_cours
    cli = _patch_client_async(monkeypatch, post, polls)
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=long"})))
    assert out["ok"] is False
    assert "délai" in out["message"].lower()
    assert out["job_id"] == "abc"


def test_appel_dynamique_async_sans_job_id_rend_honnete(monkeypatch):
    post = _Resp(202, {"statut": "en_cours"})  # pas de job_id
    cli = _patch_client_async(monkeypatch, post, [])
    out = json.loads(asyncio.run(
        outils._appel_dynamique(cli, _cap_async(), {"url": "https://youtube.com/watch?v=x"})))
    assert out["ok"] is False
    assert "job_id" in out["message"].lower() or "202" in out["message"]


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
