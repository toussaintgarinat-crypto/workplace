"""Tests de la correspondance multi-utilisateur : consentement, liaison, mode ouvert."""
import correspondance as K


def test_inconnu_non_autorise_et_code():
    r = K.resoudre("telegram", "inconnu1", "Bob")
    assert r["autorise"] is False
    assert r["statut"] == "en_attente"
    assert r["nouveau"] is True
    assert r["code"]                                  # un code de liaison est attribué
    # 2ᵉ passage : plus « nouveau », même code, toujours en attente
    r2 = K.resoudre("telegram", "inconnu1", "Bob")
    assert r2["nouveau"] is False and r2["code"] == r["code"]


def test_lier_puis_autorise():
    K.resoudre("telegram", "u2", "Alice")
    K.lier("telegram", "u2", "alice@workplace")
    r = K.resoudre("telegram", "u2", "Alice")
    assert r["autorise"] is True
    assert r["utilisateur"] == "alice@workplace"
    assert r["statut"] == "lie"


def test_lier_par_code():
    r = K.resoudre("whatsapp", "33611", "Léa")
    e = K.lier_par_code(r["code"], "lea@workplace")
    assert e is not None and e["utilisateur"] == "lea@workplace"
    assert K.resoudre("whatsapp", "33611")["autorise"] is True
    assert K.lier_par_code("ZZZZZZ", "x") is None


def test_delier():
    K.lier("discord", "d1", "u")
    assert K.delier("discord", "d1") is True
    assert K.resoudre("discord", "d1")["autorise"] is False
    assert K.delier("discord", "absent") is False


def test_mode_ouvert(monkeypatch):
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "patron")
    r = K.resoudre("telegram", "ouvert1", "Qui")
    assert r["autorise"] is True
    assert r["statut"] == "ouvert"
    assert r["utilisateur"] == "patron"


# ── S245 : droit d'approbation explicite ────────────────────────────────────────
def test_approbateur_exige_lie_et_drapeau(monkeypatch):
    K.lier("telegram", "ap-ok", "a@wp")
    assert K.definir_approbateur("telegram", "ap-ok", True) is not None
    assert K.est_approbateur("telegram", "ap-ok") is True

    K.lier("telegram", "ap-sans", "b@wp")                  # lie sans drapeau
    assert K.est_approbateur("telegram", "ap-sans") is False

    K.resoudre("telegram", "ap-attente", "C")              # en_attente + drapeau forcé
    t = K.table()
    t["telegram:ap-attente"]["approbateur"] = True
    K._sauver(t)
    assert K.est_approbateur("telegram", "ap-attente") is False

    monkeypatch.setenv("CONNEXION_OUVERT", "1")           # « ouvert » + drapeau : JAMAIS
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "patron")
    K.resoudre("telegram", "ap-ouvert", "D")
    t = K.table()
    assert t["telegram:ap-ouvert"]["statut"] == "ouvert"
    t["telegram:ap-ouvert"]["approbateur"] = True
    K._sauver(t)
    assert K.est_approbateur("telegram", "ap-ouvert") is False

    assert K.est_approbateur("telegram", "inconnu-total") is False


def test_approbateur_drapeau_truthy_non_booleen_refuse():
    K.lier("telegram", "ap-str", "e@wp")
    t = K.table()
    t["telegram:ap-str"]["approbateur"] = "true"            # pas un vrai booléen
    K._sauver(t)
    assert K.est_approbateur("telegram", "ap-str") is False


def test_approbateurs_liste_seulement_les_lies_du_reseau():
    K.lier("telegram", "lst-1", "u1")
    K.definir_approbateur("telegram", "lst-1", True)
    K.lier("telegram", "lst-2", "u2")                       # lie, pas approbateur
    K.lier("whatsapp", "lst-3", "u3")
    K.definir_approbateur("whatsapp", "lst-3", True)        # autre réseau
    K.resoudre("telegram", "lst-4", "x")                    # en attente
    t = K.table()
    t["telegram:lst-4"]["approbateur"] = True
    K._sauver(t)
    liste = K.approbateurs("telegram")
    assert "lst-1" in liste
    assert "lst-2" not in liste and "lst-3" not in liste and "lst-4" not in liste


def test_definir_approbateur_refuse_entree_inconnue_ou_non_liee():
    assert K.definir_approbateur("telegram", "n-existe-pas", True) is None
    K.resoudre("telegram", "da-attente", "Z")
    assert K.definir_approbateur("telegram", "da-attente", True) is None
    assert K.est_approbateur("telegram", "da-attente") is False


def test_definir_approbateur_peut_retirer_le_droit():
    K.lier("telegram", "ret-1", "u")
    K.definir_approbateur("telegram", "ret-1", True)
    K.definir_approbateur("telegram", "ret-1", False)
    assert K.est_approbateur("telegram", "ret-1") is False


def test_relier_meme_utilisateur_conserve_le_drapeau():
    K.lier("telegram", "rel-1", "meme@wp")
    K.definir_approbateur("telegram", "rel-1", True)
    K.lier("telegram", "rel-1", "meme@wp")
    assert K.est_approbateur("telegram", "rel-1") is True
    K.resoudre("telegram", "rel-1", "Nouveau nom")           # simple mise à jour du nom
    assert K.est_approbateur("telegram", "rel-1") is True


def test_relier_a_un_autre_utilisateur_retire_le_drapeau():
    """Changer le compte rattaché ne doit pas transmettre le droit d'approbation."""
    K.lier("telegram", "rel-2", "ancien@wp")
    K.definir_approbateur("telegram", "rel-2", True)
    K.lier("telegram", "rel-2", "autre@wp")
    assert K.est_approbateur("telegram", "rel-2") is False
    # idem par code de liaison
    K.lier("telegram", "rel-3", "ancien@wp")
    K.definir_approbateur("telegram", "rel-3", True)
    code = K.table()["telegram:rel-3"]["code"]
    K.lier_par_code(code, "autre@wp")
    assert K.est_approbateur("telegram", "rel-3") is False


def test_delier_supprime_le_droit():
    K.lier("telegram", "del-1", "u")
    K.definir_approbateur("telegram", "del-1", True)
    K.delier("telegram", "del-1")
    assert K.est_approbateur("telegram", "del-1") is False
    K.lier("telegram", "del-1", "u")                         # re-création : pas de droit hérité
    assert K.est_approbateur("telegram", "del-1") is False


def test_groupe_telegram_ne_peut_jamais_etre_approbateur():
    K.lier("telegram", "-100123", "g@wp")
    assert K.definir_approbateur("telegram", "-100123", True) is None
    assert K.est_approbateur("telegram", "-100123") is False
    t = K.table()
    t["telegram:-100124"] = {"reseau": "telegram", "id_externe": "-100124", "statut": "lie",
                             "utilisateur": "g@wp", "approbateur": True}   # forcé à la main
    K._sauver(t)
    assert "-100124" not in K.approbateurs("telegram")
