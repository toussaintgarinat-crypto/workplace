import json
import os

import pytest

import contrat_donnees as C
import stockage_pont
import studio as S
import support as SUP


@pytest.fixture
def racine(tmp_path, monkeypatch):
    """Studio entier redirigé vers un dossier jetable (séries, profils, comptes, ponts)."""
    r = str(tmp_path)
    for sous in ("profils", "comptes", "pont"):
        os.makedirs(os.path.join(r, sous))
    monkeypatch.setattr(S, "ATELIERS_DIR", r)
    monkeypatch.setattr(S, "PROFILS_DIR", os.path.join(r, "profils"))
    monkeypatch.setattr(S, "COMPTES_DIR", os.path.join(r, "comptes"))
    monkeypatch.setattr(stockage_pont, "ATELIERS_DIR", r)
    monkeypatch.setattr(stockage_pont, "PONT_DIR", os.path.join(r, "pont"))
    monkeypatch.delenv("STUDIO_KEY", raising=False)
    return r


def peupler(u):
    sid, pid = f"serie-{u}", f"profil-{u}"
    S._save({"id": sid, "titre": f"Série de {u}", "cree_par": u, "episodes": []})
    S._save_profil({"id": pid, "nom": f"Enfant de {u}", "cible": "6-8", "cree_par": u})
    S._ajouter_evenement(pid, {"type": "ecoute", "serie_id": sid})
    S._save_compte(u, {"nom_famille": f"Famille {u}"})
    stockage_pont.fixer_monde(sid, f"monde-{u}")


def test_exporter_ne_contient_que_l_utilisateur(racine):
    peupler("claire")
    peupler("marina")
    o = SUP.exporter("claire")
    assert [s["id"] for s in o["series"]] == ["serie-claire"]
    assert [p["id"] for p in o["profils"]] == ["profil-claire"]
    assert [j["profil_id"] for j in o["journaux"]] == ["profil-claire"]
    assert o["comptes"] == [{"nom_famille": "Famille claire"}]
    assert [p["serie_id"] for p in o["ponts"]] == ["serie-claire"]
    assert "marina" not in json.dumps(o)


def test_exporter_cles_toujours_presentes_meme_vide(racine):
    assert SUP.exporter("personne") == {
        "series": [], "profils": [], "journaux": [], "comptes": [], "ponts": []}


def test_export_deterministe(racine):
    peupler("claire")
    assert C.empreinte(SUP.exporter("claire")) == C.empreinte(SUP.exporter("claire"))


def test_reinitialiser_refuse_si_empreinte_differente(racine):
    peupler("claire")
    with pytest.raises(SUP.Refus) as e:
        SUP.reinitialiser("claire", "empreinte-fausse")
    assert e.value.raison == "empreinte"
    assert os.path.exists(S._path("serie-claire"))


def test_reinitialiser_efface_claire_et_pas_marina(racine):
    peupler("claire")
    peupler("marina")
    emp = C.empreinte(SUP.exporter("claire"))
    supprimes = SUP.reinitialiser("claire", emp)
    assert supprimes["series"] == 1
    assert sum(C.comptages(SUP.exporter("claire")).values()) == 0
    assert sum(C.comptages(SUP.exporter("marina")).values()) == 5


def test_reinitialiser_detecte_une_modification_apres_export(racine):
    peupler("claire")
    emp = C.empreinte(SUP.exporter("claire"))
    S._ajouter_evenement("profil-claire", {"type": "ecoute", "serie_id": "serie-claire"})
    with pytest.raises(SUP.Refus):
        SUP.reinitialiser("claire", emp)


def test_aller_retour_identique(racine):
    peupler("claire")
    avant = SUP.exporter("claire")
    SUP.reinitialiser("claire", C.empreinte(avant))
    SUP.importer("claire", avant)
    assert SUP.exporter("claire") == avant
    assert S._load("serie-claire")["titre"] == "Série de claire"   # relisible par le Studio
    assert S._load_compte("claire") == {"nom_famille": "Famille claire"}


def test_importer_refuse_objet_d_un_autre_utilisateur(racine):
    peupler("marina")
    o = SUP.exporter("marina")
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "objet_etranger"
    assert SUP.exporter("claire")["series"] == []


def test_importer_refuse_conflit_avec_un_objet_d_un_autre(racine):
    peupler("marina")
    o = {"series": [{"id": "serie-marina", "titre": "vol", "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "conflit"
    assert S._load("serie-marina")["titre"] == "Série de marina"


def test_importer_ne_garde_rien_si_refus(racine):
    peupler("marina")
    o = {"series": [{"id": "ok-1", "titre": "A", "cree_par": "claire"},
                    {"id": "serie-marina", "titre": "vol", "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus):
        SUP.importer("claire", o)
    assert not os.path.exists(S._path("ok-1"))   # rien d'écrit avant la validation complète


@pytest.mark.parametrize("mauvais_id", ["../evil", "a/b", "", "x" * 65, "a b"])
def test_importer_refuse_les_identifiants_dangereux(racine, mauvais_id):
    o = {"series": [{"id": mauvais_id, "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "format"


def test_importer_refuse_journal_orphelin(racine):
    o = {"series": [], "profils": [], "comptes": [], "ponts": [],
         "journaux": [{"profil_id": "inconnu", "evenements": []}]}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "incoherent"


def test_importer_refuse_cle_inconnue(racine):
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", {"series": [], "autre": []})
    assert e.value.raison == "format"


def test_migrer_version_courante_inchangee():
    o = {"series": []}
    assert SUP.migrer(o, "1") is o


def test_migrer_sans_crochet_refuse(monkeypatch):
    monkeypatch.setattr(SUP, "VERSION_SCHEMA", "2")
    with pytest.raises(SUP.Refus) as e:
        SUP.migrer({"series": []}, "1")
    assert e.value.raison == "migration"


def test_migrer_applique_les_crochets(monkeypatch):
    monkeypatch.setattr(SUP, "VERSION_SCHEMA", "3")
    monkeypatch.setattr(SUP, "MIGRATIONS", {
        1: lambda o: {**o, "v2": True}, 2: lambda o: {**o, "v3": True}})
    assert SUP.migrer({"series": []}, "1") == {"series": [], "v2": True, "v3": True}


def test_verifier_valide_et_ne_touche_pas_le_vrai_volume(racine):
    peupler("claire")
    objets = SUP.exporter("claire")
    paquet = C.construire_paquet("studio", "claire", "1", objets, b"k")
    SUP.reinitialiser("claire", C.empreinte(objets))        # espace réel vide
    rapport = SUP.verifier(paquet, b"k", "claire")
    assert rapport["ok"] and rapport["comptages"]["series"] == 1
    assert rapport["empreinte"] == C.empreinte(objets)
    assert SUP.exporter("claire")["series"] == []           # la vérification n'a rien écrit


def test_verifier_refuse_paquet_falsifie(racine):
    peupler("claire")
    paquet = C.construire_paquet("studio", "claire", "1", SUP.exporter("claire"), b"k")
    with pytest.raises(C.PaquetInvalide):
        SUP.verifier(paquet, b"autre-cle", "claire")


def test_exporter_ignore_un_id_non_sur_dans_un_fichier(racine):
    """Un id de fichier forgé ne doit jamais servir à fabriquer un chemin (reset)."""
    with open(os.path.join(racine, "forge.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "../evil", "cree_par": "claire"}, f)
    assert SUP.exporter("claire")["series"] == []
