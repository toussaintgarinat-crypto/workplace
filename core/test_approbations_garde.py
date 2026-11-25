"""La garde des capacités sensibles, DANS outils.executer (S245) — là où le trou vivait.

Même méthode que test_gate_action_bout_en_bout : on prouve le câblage, puis on vérifie que
neutraliser la garde fait échouer les tests de sécurité (et pas ceux de non-régression)."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "dokploy": {"nom": "dokploy", "port": 6300, "capacites": [
        {"nom": "app_redemarrer", "chemin": "/redemarrer", "methode": "POST", "action": True,
         "sensibilite": "reversible", "description": "Redémarre une app.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_reset", "chemin": "/reset", "methode": "POST", "action": True,
         "sensibilite": "destructif", "description": "Remise à zéro.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_logs", "chemin": "/logs", "sensibilite": "lecture",
         "description": "Lit les logs.", "params": {"app": {"type": "string"}}},
        {"nom": "app_ancienne", "chemin": "/x", "methode": "POST", "action": True,
         "description": "Action SANS sensibilite (comportement historique).",
         "params": {"app": {"type": "string"}}},
    ]},
})


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    notifs = []

    async def faux_notifier(registre, demande):
        notifs.append(demande["id"])

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    atteints = []

    async def faux_executer(nom, args, registre):
        atteints.append((nom, dict(args)))
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_executer", faux_executer)
    return {"notifs": notifs, "atteints": atteints}


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def test_est_sensible_lit_le_manifeste():
    assert outils.est_sensible("app_redemarrer", REGISTRE) == "reversible"
    assert outils.est_sensible("app_reset", REGISTRE) == "destructif"
    assert outils.est_sensible("app_logs", REGISTRE) is None       # lecture
    assert outils.est_sensible("app_ancienne", REGISTRE) is None   # pas de champ
    assert outils.est_sensible("inconnu", REGISTRE) is None


# ── Sécurité ─────────────────────────────────────────────────────────────────

def test_sans_approbation_rien_ne_s_execute_et_une_demande_est_creee(_env):
    res = _run("app_redemarrer", {"app": "crm", "confirme": True})   # même avec confirme=true
    assert _env["atteints"] == []
    assert "NON exécutée" in res and "Telegram" in res
    assert len(_env["notifs"]) == 1
    assert approbations.lire(_env["notifs"][0])["statut"] == "en_attente"


def test_le_llm_ne_peut_pas_se_confirmer_tout_seul(_env):
    for _ in range(3):
        _run("app_redemarrer", {"app": "crm", "confirme": True})
    assert _env["atteints"] == []
    assert len(_env["notifs"]) == 1          # une seule demande, pas de spam


def test_approuvee_puis_executee_une_fois(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    res = _run("app_redemarrer", {"app": "crm"})
    assert _env["atteints"] == [("app_redemarrer", {"app": "crm", "confirme": True})]
    assert '"ok": true' in res
    _run("app_redemarrer", {"app": "crm"})                           # usage unique
    assert len(_env["atteints"]) == 1


def test_approbation_pour_crm_ne_vaut_pas_pour_autre(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    _run("app_redemarrer", {"app": "autre"})
    assert _env["atteints"] == []


def test_refus_bloque_la_redemande_immediate(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.refuser(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    res = _run("app_redemarrer", {"app": "crm"})
    assert "refusé" in res.lower()
    assert len(_env["notifs"]) == 1 and _env["atteints"] == []


def test_destructif_exige_le_code_pas_le_bouton(_env):
    _run("app_reset", {"app": "crm"})
    id_ = _env["notifs"][0]
    assert approbations.approuver(id_, "tg:42", "telegram", utilisateur="perso") == (False, "code_requis")
    _run("app_reset", {"app": "crm"})
    assert _env["atteints"] == []
    approbations.armer_saisie_code(id_, "tg:42", utilisateur="perso")
    approbations.valider_code_saisi("tg:42", approbations.lire(id_)["code"], utilisateur="perso")
    _run("app_reset", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_reset"]


def test_un_echec_d_execution_est_journalise(_env, monkeypatch):
    async def casse(nom, args, registre):
        return "Erreur (dokploy) : boom"

    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    monkeypatch.setattr(outils, "_executer", casse)
    _run("app_redemarrer", {"app": "crm"})
    assert approbations.lire(_env["notifs"][0])["statut"] == "echec"


# ── Non-régression (doivent passer AVANT et APRÈS la garde) ──────────────────

def test_lecture_passe_sans_approbation(_env):
    _run("app_logs", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_logs"] and _env["notifs"] == []


def test_capacite_sans_sensibilite_garde_le_comportement_historique(_env):
    _run("app_ancienne", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_ancienne"] and _env["notifs"] == []


# ── La garde ne doit pas dépendre du LLM ─────────────────────────────────────

def test_exiger_direct():
    id_, msg, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id_ is None and msg and nouvelle["statut"] == "en_attente"
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id2 is None and msg2 and nouvelle2 is None          # déjà en attente : pas de doublon


def test_approbation_reversible_ne_debloque_pas_destructif():
    id_, _, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "r")
    approbations.approuver(nouvelle["id"], "tg:42", "telegram", utilisateur="perso")
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "destructif", "r")
    assert id2 is None and msg2 and nouvelle2["statut"] == "en_attente"
    assert nouvelle2["sensibilite"] == "destructif"


def test_refus_reversible_ne_bloque_pas_destructif():
    _, _, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "r")
    approbations.refuser(nouvelle["id"], "tg:42", "telegram", utilisateur="perso")
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "destructif", "r")
    assert id2 is None and nouvelle2 is not None and "REFUSÉ" not in msg2


# ── Revue Task 3 : fail closed, conclure et notification robustes ────────────

def _registre_sens(valeur):
    cap = {"nom": "cap_x", "chemin": "/x", "methode": "POST", "action": True,
           "description": "x", "params": {"app": {"type": "string"}}}
    if valeur != "ABSENT":
        cap["sensibilite"] = valeur
    return _FauxRegistre({"b": {"nom": "b", "port": 6999, "capacites": [cap]}})


@pytest.mark.parametrize("valeur", ["destructive", "high", True, "", 3, "supprimer"])
def test_sensibilite_invalide_est_destructif_fail_closed(valeur, caplog):
    with caplog.at_level("WARNING"):
        assert outils.est_sensible("cap_x", _registre_sens(valeur)) == "destructif"
    assert "cap_x" in caplog.text


@pytest.mark.parametrize("valeur,attendu", [
    ("Destructif", "destructif"), ("destructif ", "destructif"),
    (" reversible ", "reversible"), ("DONNEES", "donnees"),
])
def test_sensibilite_normalisee(valeur, attendu):
    assert outils.est_sensible("cap_x", _registre_sens(valeur)) == attendu


@pytest.mark.parametrize("valeur", ["lecture", "Lecture ", None, "ABSENT"])
def test_sensibilite_lecture_ou_absente_non_gardee(valeur):
    assert outils.est_sensible("cap_x", _registre_sens(valeur)) is None


def test_typo_sensibilite_exige_une_approbation(_env):
    reg = _registre_sens("destructive")
    res = asyncio.run(outils.executer("cap_x", {"app": "a"}, reg))
    assert _env["atteints"] == [] and "NON exécutée" in res
    assert approbations.lire(_env["notifs"][0])["sensibilite"] == "destructif"


def test_conclure_meme_si_executer_leve(_env, monkeypatch):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")

    async def annule(nom, args, registre):
        raise asyncio.CancelledError()

    monkeypatch.setattr(outils, "_executer", annule)
    with pytest.raises(asyncio.CancelledError):
        _run("app_redemarrer", {"app": "crm"})
    ligne = approbations.lire(_env["notifs"][0])
    assert ligne["statut"] == "echec"
    assert "interrompue" in str(ligne.get("resultat", "")) + str(ligne)


def test_notification_en_echec_ne_se_propage_pas(_env, monkeypatch):
    async def casse(registre, demande):
        raise RuntimeError("telegram HS")

    monkeypatch.setattr(outils, "_notifier_approbation", casse)
    res = _run("app_redemarrer", {"app": "crm"})
    assert "NON exécutée" in res and _env["atteints"] == []


# ── Résumé expurgé des secrets (revue Task 5) ────────────────────────────────

def test_resume_expurge_les_cles_sensibles():
    r = outils._resume_action("x", {"password": "hunter2", "api_key": "abc", "token": "t0k",
                                    "app": "crm", "db_dsn": "pg://u@h/d"})
    for secret in ("hunter2", "abc", "t0k", "pg://u@h/d"):
        assert secret not in r
    assert "app='crm'" in r and "'***'" in r


def test_resume_masque_url_avec_identifiants_et_jeton_opaque():
    r = outils._resume_action("x", {"cible": "postgres://bob:s3cr3tpw@db.local/x",
                                    "valeur": "A" * 40})
    assert "s3cr3tpw" not in r and "A" * 40 not in r
    assert "bob" in r and "db.local" in r


def test_resume_tronque_les_longues_valeurs():
    r = outils._resume_action("x", {"note": "mot " * 100})
    assert len(r) < 150


def test_resume_args_ordinaires_inchanges():
    assert outils._resume_action("app_reset", {"app": "crm"}) == "app_reset(app='crm')"


def test_resume_expurge_recursivement_dict_liste_query_bearer():
    r = outils._resume_action("x", {
        "opts": {"password": "hunter2"},
        "h": {"Authorization": "Bearer abc"},
        "l": ["postgres://u:pw@h/d"],
        "u": "https://h/?token=abc123&page=2",
        "txt": "envoie Authorization: Bearer xyz789 ici",
        "imbr": [{"api_key": "kkk111", "n": 1}],
        "cles": {1: "ok", ("a", "b"): "x"},
    })
    for secret in ("hunter2", "Bearer abc", "u:pw@", "abc123", "xyz789", "kkk111"):
        assert secret not in r, secret
    assert "Bearer ***" in r and "page=2" in r and "'n': 1" in r


def test_resume_profondeur_bornee():
    prof = {}
    cur = prof
    for _ in range(20):
        cur["a"] = {}
        cur = cur["a"]
    cur["password"] = "deepsecret"
    r = outils._resume_action("x", {"p": prof})
    assert "deepsecret" not in r


def test_resume_args_ordinaires_imbriques_inchanges():
    assert outils._resume_action("x", {"app": "crm", "opts": {"replicas": 2}}) == \
        "x(app='crm', opts={'replicas': 2})"


def test_secrets_differents_empreintes_differentes_resume_masque(_env):
    _run("app_redemarrer", {"app": "crm", "password": "secret-un"})
    _run("app_redemarrer", {"app": "crm", "password": "secret-deux"})
    assert len(_env["notifs"]) == 2                     # deux demandes distinctes
    d1, d2 = (approbations.lire(i) for i in _env["notifs"])
    assert d1["empreinte"] != d2["empreinte"]
    for d in (d1, d2):
        assert "secret-un" not in d["resume"] and "secret-deux" not in d["resume"]
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    _run("app_redemarrer", {"app": "crm", "password": "secret-deux"})
    assert _env["atteints"] == []                       # l'approbation ne vaut que pour secret-un
    _run("app_redemarrer", {"app": "crm", "password": "secret-un"})
    assert len(_env["atteints"]) == 1


# ── Revue finale : mise à jour finale du canal, origine ──────────────────────

def test_message_telegram_edite_apres_execution(_env, monkeypatch):
    vus = []

    async def maj(registre, demande):
        vus.append((demande["statut"], approbations_canal.texte_final(demande)))

    monkeypatch.setattr(approbations_canal, "mettre_a_jour", maj)
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    res = _run("app_redemarrer", {"app": "crm"})
    assert '"ok": true' in res
    assert len(vus) == 1 and vus[0][0] == "executee" and "✅ Exécutée" in vus[0][1]


def test_message_final_echec_et_panne_canal_sans_effet_sur_le_resultat(_env, monkeypatch):
    async def casse(nom, args, registre):
        return "Erreur (dokploy) : boom"

    async def maj_ko(registre, demande):
        raise RuntimeError("telegram down")

    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram", utilisateur="perso")
    monkeypatch.setattr(outils, "_executer", casse)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", maj_ko)
    assert _run("app_redemarrer", {"app": "crm"}) == "Erreur (dokploy) : boom"
    assert "⚠️ Échec" in approbations_canal.texte_final(
        approbations.lire(_env["notifs"][0]))


def test_origine_tracee_par_les_points_d_entree(_env, monkeypatch):
    import mcp as mcp_mod
    # Chemin réel du MCP : tools/call -> avec_origine("mcp") -> outils.executer -> exiger.
    monkeypatch.setattr(mcp_mod, "lister_outils", lambda registre: [{"name": "app_redemarrer"}])
    asyncio.run(mcp_mod.traiter({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "app_redemarrer",
                                            "arguments": {"app": "crm"}}}, REGISTRE))
    assert [d["origine"] for d in approbations.en_attente()] == ["mcp"]
    assert approbations.ORIGINE.get() == "inconnue"
