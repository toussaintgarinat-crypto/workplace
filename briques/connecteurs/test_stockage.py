"""Stockage : isolation par tenant, curseurs, comptabilité des syncs (S214)."""
import pytest

import stockage


@pytest.fixture(autouse=True)
def _base_vierge():
    stockage.DB_CHEMIN.unlink(missing_ok=True)
    stockage.initialiser()
    yield


def _source(tenant="alice", nom="mon-github"):
    return stockage.creer_source(tenant, nom, "source-github",
                                 {"credentials": {"personal_access_token": "ghp_x"}}, ["issues"])


# ── Isolation ────────────────────────────────────────────────────────────────

def test_une_personne_ne_voit_pas_les_sources_d_une_autre():
    _source("alice")
    _source("bob", "sa-source")
    assert [s["nom"] for s in stockage.lister_sources("alice")] == ["mon-github"]
    assert [s["nom"] for s in stockage.lister_sources("bob")] == ["sa-source"]


def test_on_ne_lit_pas_la_source_d_une_autre_personne_par_son_id():
    src = _source("alice")
    assert stockage.source_get("bob", src["id"]) is None
    assert stockage.config_de("bob", src["id"]) is None


def test_on_ne_supprime_pas_la_source_d_une_autre_personne():
    src = _source("alice")
    assert stockage.supprimer_source("bob", src["id"]) is False
    assert stockage.source_get("alice", src["id"]) is not None


def test_deux_personnes_peuvent_avoir_une_source_du_meme_nom():
    """L'unicité est par (tenant, nom) — pas globale, sinon la 2e personne serait bloquée."""
    _source("alice", "github")
    _source("bob", "github")
    assert len(stockage.sources_actives()) == 2


def test_le_meme_nom_deux_fois_pour_la_meme_personne_est_refuse():
    _source("alice", "github")
    with pytest.raises(Exception, match="UNIQUE"):
        _source("alice", "github")


# ── Les identifiants ne ressortent jamais ────────────────────────────────────

def test_la_config_n_est_jamais_rendue_en_clair_par_une_vue():
    src = _source()
    assert src["config"] == {"credentials": "(renseigné)"}
    assert "ghp_x" not in str(stockage.lister_sources("alice"))
    assert "ghp_x" not in str(stockage.source_get("alice", src["id"]))


def test_config_de_rend_le_clair_car_c_est_le_pont_qui_appelle():
    src = _source()
    connecteur, config, flux = stockage.config_de("alice", src["id"])
    assert connecteur == "source-github"
    assert config["credentials"]["personal_access_token"] == "ghp_x"
    assert flux == ["issues"]


def test_le_secret_n_est_pas_lisible_dans_le_fichier_sqlite():
    """Chiffrement AU REPOS : on lit les octets du fichier, pas l'API."""
    _source()
    assert b"ghp_x" not in stockage.DB_CHEMIN.read_bytes()


# ── Curseurs ─────────────────────────────────────────────────────────────────

def test_enregistrer_puis_relire_un_curseur():
    src = _source()
    stockage.enregistrer_etat(src["id"], "issues", {"updated_at": "2026-07-28T00:00:00Z"})
    assert stockage.lire_etats(src["id"]) == {"issues": {"updated_at": "2026-07-28T00:00:00Z"}}


def test_le_curseur_est_ecrase_pas_dupplique():
    src = _source()
    stockage.enregistrer_etat(src["id"], "issues", {"n": 1})
    stockage.enregistrer_etat(src["id"], "issues", {"n": 2})
    assert stockage.lire_etats(src["id"]) == {"issues": {"n": 2}}


def test_eteindre_une_source_ne_touche_pas_a_son_curseur():
    """Le point de la capacité `connecteurs_source_activer` : rallumée, elle reprend."""
    src = _source()
    stockage.enregistrer_etat(src["id"], "issues", {"n": 7})
    stockage.modifier_source("alice", src["id"], active=False)
    assert stockage.sources_actives() == []
    assert stockage.lire_etats(src["id"]) == {"issues": {"n": 7}}
    stockage.modifier_source("alice", src["id"], active=True)
    assert stockage.sources_actives() == [("alice", src["id"])]


def test_supprimer_la_source_emporte_curseurs_et_syncs():
    src = _source()
    stockage.enregistrer_etat(src["id"], "issues", {"n": 1})
    stockage.cloturer_sync(stockage.ouvrir_sync("alice", src["id"]), "ok")
    stockage.supprimer_source("alice", src["id"])
    assert stockage.lire_etats(src["id"]) == {}
    assert stockage.lister_syncs("alice") == []


def test_oublier_les_curseurs():
    src = _source()
    stockage.enregistrer_etat(src["id"], "issues", {"n": 1})
    assert stockage.oublier_etats(src["id"]) == 1
    assert stockage.lire_etats(src["id"]) == {}


# ── Comptabilité des syncs ───────────────────────────────────────────────────

def test_cycle_de_vie_d_une_sync():
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    assert stockage.sync_get("alice", sid)["statut"] == "en_cours"
    stockage.cloturer_sync(sid, "ok", nb_enregistrements=42)
    fini = stockage.sync_get("alice", sid)
    assert (fini["statut"], fini["nb_enregistrements"]) == ("ok", 42)
    assert fini["fin"] is not None


def test_un_statut_inconnu_est_refuse():
    src = _source()
    with pytest.raises(ValueError):
        stockage.cloturer_sync(stockage.ouvrir_sync("alice", src["id"]), "presque")


def test_une_sync_en_cours_au_demarrage_est_declaree_interrompue():
    """Le conteneur a redémarré en plein transfert : la ligne doit cesser de mentir
    « en cours », sans quoi l'opérateur ne distingue plus une sync vivante d'une morte."""
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    assert stockage.rouvrir_syncs_orphelines() == 1
    reprise = stockage.sync_get("alice", sid)
    assert reprise["statut"] == "interrompue"
    assert "curseur" in reprise["erreur"]


def test_une_sync_deja_close_n_est_pas_rouverte():
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.cloturer_sync(sid, "ok")
    assert stockage.rouvrir_syncs_orphelines() == 0
    assert stockage.sync_get("alice", sid)["statut"] == "ok"


def test_le_volume_d_une_sync_interrompue_n_est_pas_perdu():
    """`avancer_sync` : sans lui, une sync tuée rapporterait 0 alors qu'elle a transféré."""
    src = _source()
    sid = stockage.ouvrir_sync("alice", src["id"])
    stockage.avancer_sync(sid, 1200)
    stockage.rouvrir_syncs_orphelines()
    assert stockage.sync_get("alice", sid)["nb_enregistrements"] == 1200


def test_lister_les_syncs_est_scope_au_tenant():
    a = _source("alice")
    b = _source("bob", "sa-source")
    stockage.ouvrir_sync("alice", a["id"])
    stockage.ouvrir_sync("bob", b["id"])
    assert len(stockage.lister_syncs("alice")) == 1
    assert len(stockage.lister_syncs("bob")) == 1


def test_lister_les_syncs_filtre_par_source_et_rend_la_plus_recente_d_abord():
    a, b = _source("alice", "s1"), _source("alice", "s2")
    stockage.ouvrir_sync("alice", a["id"])
    dernier = stockage.ouvrir_sync("alice", b["id"])
    assert stockage.lister_syncs("alice")[0]["id"] == dernier
    assert [s["source_id"] for s in stockage.lister_syncs("alice", a["id"])] == [a["id"]]


# ── venture_id (S230) ────────────────────────────────────────────────────────

def test_creer_source_avec_venture_id():
    src = stockage.creer_source("alice", "hubspot", "source-hubspot",
                                {"credentials": {"access_token": "x"}}, ["contacts", "deals"],
                                venture_id="vt-client-a")
    assert src["venture_id"] == "vt-client-a"


def test_creer_source_sans_venture_id_reste_valide():
    """Non-régression : une source « ancien format » (sans venture_id) reste valide,
    comme toute évolution de schéma dans ce parc (cf. modifier_source déjà tolérant)."""
    src = _source()
    assert src["venture_id"] is None


def test_venture_id_de_rend_le_lien_ou_none():
    src = stockage.creer_source("alice", "hubspot2", "source-hubspot", {}, [],
                                venture_id="vt-x")
    assert stockage.venture_id_de(src["id"]) == "vt-x"
    autre = _source("alice", "sans-venture")
    assert stockage.venture_id_de(autre["id"]) is None


def test_modifier_source_peut_relier_a_une_venture():
    src = _source()
    stockage.modifier_source("alice", src["id"], venture_id="vt-nouveau")
    assert stockage.source_get("alice", src["id"])["venture_id"] == "vt-nouveau"
