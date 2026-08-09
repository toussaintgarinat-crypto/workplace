"""Le gate humain structurel (S222).

Le test qui compte est `test_le_trou_de_s221_est_ferme` : avant ce sprint, un LLM pouvait
appeler une action avec `confirme=true` de sa propre initiative et elle partait vraiment.
"""

import time

import pytest

import accord_action
from accord_action import Registre


@pytest.fixture
def reg():
    return Registre()


ARGS = {"destinataire": "alice@exemple.fr", "corps": "Bonjour"}


# ── La garantie centrale ─────────────────────────────────────────────────────

def test_le_trou_de_s221_est_ferme(reg):
    """Sans demande préalable ni tour de parole humain, `confirme=true` ne passe pas.
    C'est exactement ce que le gate déclaratif laissait passer."""
    ok, msg = reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})
    assert ok is False
    assert "aucun accord" in msg


def test_demander_seul_ne_suffit_pas(reg):
    """Le LLM ne peut pas jouer les deux rôles : demander PUIS se confirmer tout seul,
    dans le même tour, sans que l'humain ait dit quoi que ce soit."""
    reg.demander("fil-1", "mail_envoyer", ARGS)
    ok, msg = reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})
    assert ok is False
    assert "n'a pas encore répondu" in msg


def test_le_parcours_complet_autorise_l_action(reg):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui vas-y")
    ok, msg = reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})
    assert ok is True and msg is None


def test_un_tour_utilisateur_sans_demande_n_accorde_rien(reg):
    """Dire « oui » dans le vide ne crée pas un accord utilisable plus tard."""
    reg.tour_utilisateur("fil-1", "oui")
    reg.demander("fil-1", "mail_envoyer", ARGS)
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is False


# ── L'accord porte sur des arguments précis ──────────────────────────────────

def test_un_accord_ne_se_reporte_pas_sur_une_autre_cible(reg):
    """L'utilisateur accepte d'écrire à Alice ; le LLM ne peut pas écrire à Bob avec ça.
    C'est le pendant du « seuil 1 sur les mutations en masse » : N cibles = N accords."""
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui")
    autre = {**ARGS, "destinataire": "bob@exemple.fr", "confirme": True}
    assert reg.consommer("fil-1", "mail_envoyer", autre)[0] is False
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is True


def test_un_accord_ne_se_reporte_pas_sur_une_autre_capacite(reg):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui")
    assert reg.consommer("fil-1", "mail_supprimer", {**ARGS, "confirme": True})[0] is False


def test_accord_a_usage_unique(reg):
    """Un « oui » n'autorise pas deux envois identiques — sinon une boucle du LLM
    déclencherait N fois la même action avec un seul accord."""
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui")
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is True
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is False


def test_accord_cloisonne_par_fil(reg):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui")
    assert reg.consommer("fil-2", "mail_envoyer", {**ARGS, "confirme": True})[0] is False


def test_deux_personnes_du_meme_fil_web_ne_partagent_pas_leurs_accords(reg):
    """`journal_conversations.fil()` vaut « web:dashboard » pour TOUTE la surface web :
    sans la personne dans la clé, le « oui » d'Alice validerait l'action de Bob."""
    alice = accord_action.cle("web:dashboard", "alice")
    bob = accord_action.cle("web:dashboard", "bob")
    assert alice != bob

    reg.demander(bob, "mail_envoyer", ARGS)          # Bob déclenche une action
    reg.tour_utilisateur(alice, "oui")               # Alice répond « oui » à autre chose
    assert reg.consommer(bob, "mail_envoyer", {**ARGS, "confirme": True})[0] is False

    reg.tour_utilisateur(bob, "oui")
    assert reg.consommer(bob, "mail_envoyer", {**ARGS, "confirme": True})[0] is True


def test_une_session_anonyme_ne_se_fond_pas_dans_les_sessions_identifiees():
    assert accord_action.cle("web:dashboard", None) != accord_action.cle("web:dashboard", "alice")


def test_empreinte_ignore_confirme_et_les_valeurs_nulles():
    """`_appel_dynamique` filtre déjà les `None` : deux appels qui partiront identiques
    doivent avoir la même empreinte, sinon l'accord ne matcherait jamais."""
    a = accord_action.empreinte("x", {"a": 1})
    assert a == accord_action.empreinte("x", {"a": 1, "confirme": True})
    assert a == accord_action.empreinte("x", {"a": 1, "b": None})
    assert a != accord_action.empreinte("x", {"a": 2})


def test_empreinte_insensible_a_l_ordre_des_arguments():
    assert (accord_action.empreinte("x", {"a": 1, "b": 2})
            == accord_action.empreinte("x", {"b": 2, "a": 1}))


# ── Refus ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reponse", [
    "non", "Non merci", "annule", "ANNULÉ", "surtout pas", "laisse tomber",
    "stop", "arrête", "pas maintenant", "n'envoie pas ça",
])
def test_un_refus_revoque_la_demande(reg, reponse):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", reponse)
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is False


def test_le_refus_est_insensible_aux_accents_et_a_la_casse():
    """Piège déjà payé une fois sur l'opt-out mail : « ANNULÉ » doit valoir « annule »."""
    assert accord_action.est_refus("ANNULÉ")
    assert accord_action.est_refus("Arrête tout")


@pytest.mark.parametrize("reponse", [
    "oui", "vas-y", "ok confirme", "oui mais pas à Bob", "d'accord",
])
def test_un_accord_nuance_n_est_pas_pris_pour_un_refus(reg, reponse):
    """« oui mais pas à Bob » contient « pas » : un motif trop large en ferait un refus
    incompréhensible pour l'utilisateur. Le LLM reste juge du sens."""
    assert not accord_action.est_refus(reponse)


# ── Expiration ───────────────────────────────────────────────────────────────

def test_un_accord_expire(reg, monkeypatch):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "oui")
    monkeypatch.setattr(accord_action, "TTL_SECONDES", 0)
    time.sleep(0.01)
    assert reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})[0] is False


def test_demandes_empilees_dedupliquees(reg):
    for _ in range(5):
        reg.demander("fil-1", "mail_envoyer", ARGS)
    assert reg.etat("fil-1")["en_attente"] == ["mail_envoyer"]


def test_etat_expose_attente_et_accord(reg):
    reg.demander("fil-1", "mail_envoyer", ARGS)
    assert reg.etat("fil-1") == {"en_attente": ["mail_envoyer"], "accordees": []}
    reg.tour_utilisateur("fil-1", "oui")
    assert reg.etat("fil-1") == {"en_attente": [], "accordees": ["mail_envoyer"]}


# ── Lectures en lot (consultatif) ────────────────────────────────────────────

def test_lecture_en_lot_annote_au_seuil_puis_se_tait(reg, monkeypatch):
    monkeypatch.setattr(accord_action, "SEUIL_LECTURE_LOT", 3)
    assert reg.noter_lecture("fil-1", "mail_lister") is None
    assert reg.noter_lecture("fil-1", "mail_lister") is None
    assert "3×" in reg.noter_lecture("fil-1", "mail_lister")
    assert reg.noter_lecture("fil-1", "mail_lister") is None  # une seule fois


def test_les_compteurs_de_lecture_repartent_au_tour_suivant(reg, monkeypatch):
    monkeypatch.setattr(accord_action, "SEUIL_LECTURE_LOT", 2)
    reg.noter_lecture("fil-1", "mail_lister")
    reg.tour_utilisateur("fil-1", "et ensuite ?")
    assert reg.noter_lecture("fil-1", "mail_lister") is None
