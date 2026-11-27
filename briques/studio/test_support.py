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


def test_export_deterministe_quel_que_soit_l_ordre_de_creation(racine, tmp_path_factory, monkeypatch):
    def construire(ordre):
        r = str(tmp_path_factory.mktemp("r"))
        for sous in ("profils", "comptes", "pont"):
            os.makedirs(os.path.join(r, sous))
        monkeypatch.setattr(S, "ATELIERS_DIR", r)
        monkeypatch.setattr(S, "PROFILS_DIR", os.path.join(r, "profils"))
        monkeypatch.setattr(S, "COMPTES_DIR", os.path.join(r, "comptes"))
        monkeypatch.setattr(stockage_pont, "ATELIERS_DIR", r)
        monkeypatch.setattr(stockage_pont, "PONT_DIR", os.path.join(r, "pont"))
        for n in ordre:
            S._save({"id": f"s{n}", "titre": f"T{n}", "cree_par": "claire", "episodes": []})
            S._save_profil({"id": f"p{n}", "nom": f"N{n}", "cible": "6-8", "cree_par": "claire"})
            stockage_pont.fixer_monde(f"s{n}", f"m{n}")
        return SUP.exporter("claire", r)
    e1, e2 = construire([1, 2, 3]), construire([3, 1, 2])
    assert e1 == e2 and C.empreinte(e1) == C.empreinte(e2)


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


@pytest.mark.parametrize("mauvais_id", ["../evil", "a/b", "", "x" * 65, "a b", "a\n"])
def test_importer_refuse_les_identifiants_dangereux(racine, mauvais_id):
    o = {"series": [{"id": mauvais_id, "cree_par": "claire"}],
         "profils": [], "journaux": [], "comptes": [], "ponts": []}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "format"
    assert [f for f in os.listdir(racine) if f.endswith(".json")] == []


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
    peupler("marina")
    avant = {u: SUP.exporter(u) for u in ("claire", "marina")}
    rapport = SUP.verifier(paquet, b"k", "claire")
    assert rapport["ok"] and rapport["comptages"]["series"] == 1
    assert rapport["empreinte"] == C.empreinte(objets)
    assert {u: SUP.exporter(u) for u in ("claire", "marina")} == avant   # rien écrit


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


def _ecrire_json(chemin, data):
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_reinitialiser_garde_un_journal_au_profil_id_different(racine):
    peupler("claire")
    chemin = os.path.join(racine, "profils", "profil-claire-journal.json")
    _ecrire_json(chemin, {"profil_id": "autre", "evenements": []})
    emp = C.empreinte(SUP.exporter("claire"))
    SUP.reinitialiser("claire", emp)
    assert os.path.exists(chemin)


def test_reinitialiser_garde_un_pont_au_serie_id_different(racine):
    peupler("claire")
    chemin = os.path.join(racine, "pont", "serie-claire.json")
    _ecrire_json(chemin, {"serie_id": "autre", "monde": "x"})
    emp = C.empreinte(SUP.exporter("claire"))
    SUP.reinitialiser("claire", emp)
    assert os.path.exists(chemin)


def test_fichier_serie_forge_ni_exporte_ni_cause_de_suppression(racine):
    peupler("marina")
    _ecrire_json(os.path.join(racine, "forge.json"), {"id": "serie-marina", "cree_par": "claire"})
    avant_marina = SUP.exporter("marina")
    o = SUP.exporter("claire")
    assert o["series"] == []
    SUP.reinitialiser("claire", C.empreinte(o))
    assert os.path.exists(S._path("serie-marina"))
    assert SUP.exporter("marina") == avant_marina


def test_fichier_profil_forge_ni_exporte_ni_cause_de_suppression(racine):
    peupler("marina")
    _ecrire_json(os.path.join(racine, "profils", "forge.json"),
                 {"id": "profil-marina", "cree_par": "claire"})
    avant_marina = SUP.exporter("marina")
    o = SUP.exporter("claire")
    assert o["profils"] == []
    SUP.reinitialiser("claire", C.empreinte(o))
    assert os.path.exists(os.path.join(racine, "profils", "profil-marina.json"))
    assert os.path.exists(os.path.join(racine, "profils", "profil-marina-journal.json"))
    assert SUP.exporter("marina") == avant_marina


VIDE = {"series": [], "profils": [], "journaux": [], "comptes": [], "ponts": []}


@pytest.mark.parametrize("cle,obj", [
    ("series", {"id": "a", "cree_par": "claire"}),
    ("profils", {"id": "a", "cree_par": "claire"}),
    ("journaux", {"profil_id": "p", "evenements": []}),
    ("ponts", {"serie_id": "s"}),
])
def test_importer_refuse_les_doublons(racine, cle, obj):
    o = {**VIDE, "series": [{"id": "s", "cree_par": "claire"}],
         "profils": [{"id": "p", "cree_par": "claire"}]}
    if cle in ("series", "profils"):
        o[cle] = [obj, dict(obj)]
    else:
        o[cle] = [obj, dict(obj)]
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "format"


def test_importer_refuse_si_la_cible_existe_mais_est_illisible(racine):
    with open(S._path("ok-1"), "w", encoding="utf-8") as f:
        f.write("{corrompu")
    o = {**VIDE, "series": [{"id": "ok-1", "cree_par": "claire"}]}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "conflit"
    with open(S._path("ok-1"), encoding="utf-8") as f:
        assert f.read() == "{corrompu"


@pytest.mark.parametrize("mauvais", ["../evil", "a/b", "", "x" * 65, "a b", "a\n"])
def test_importer_refuse_journal_ou_pont_a_id_dangereux(racine, mauvais):
    for o in ({**VIDE, "journaux": [{"profil_id": mauvais}]},
              {**VIDE, "ponts": [{"serie_id": mauvais}]},
              {**VIDE, "profils": [{"id": mauvais, "cree_par": "claire"}]}):
        with pytest.raises(SUP.Refus) as e:
            SUP.importer("claire", o)
        assert e.value.raison in ("incoherent", "format")


# ── Revue finale : collision -journal, ids non-str, identité legacy ──
def test_profil_en_journal_ne_peut_pas_ecrire_chez_un_autre(racine):
    S._save_profil({"id": "pb", "nom": "B", "cible": "6-8", "cree_par": "marina"})
    o = {**VIDE, "profils": [{"id": "pb-journal", "cree_par": "claire"}]}
    with pytest.raises(SUP.Refus) as e:
        SUP.importer("claire", o)
    assert e.value.raison == "format"
    assert not os.path.exists(os.path.join(racine, "profils", "pb-journal.json"))


def test_profil_dont_l_id_finit_par_journal_n_est_pas_exporte(racine):
    with open(os.path.join(racine, "profils", "x-journal.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "x-journal", "cree_par": "claire"}, f)
    assert SUP.exporter("claire", racine)["profils"] == []


@pytest.mark.parametrize("faux", [["a"], {"a": 1}, None, 3])
def test_importer_refuse_ids_non_str_proprement(racine, faux):
    for o in ({**VIDE, "journaux": [{"profil_id": faux}]},
              {**VIDE, "ponts": [{"serie_id": faux}]}):
        with pytest.raises(SUP.Refus) as e:
            SUP.importer("claire", o)
        assert e.value.raison == "incoherent"


def test_identite_legacy_perso(racine, monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-brute")
    for sid, cp in (("s-pub", "public"), ("s-brute", "cle-brute")):
        S._save({"id": sid, "titre": sid, "cree_par": cp, "episodes": []})
    S._save({"id": "s-sans", "titre": "x", "episodes": []})
    S._save({"id": "s-marina", "titre": "m", "cree_par": "marina", "episodes": []})
    o = SUP.exporter("perso")
    assert sorted(s["id"] for s in o["series"]) == ["s-brute", "s-pub", "s-sans"]
    assert [s["id"] for s in SUP.exporter("marina")["series"]] == ["s-marina"]
    SUP.reinitialiser("perso", C.empreinte(o))
    assert SUP.exporter("perso")["series"] == []
    assert os.path.exists(S._path("s-marina"))
    SUP.importer("perso", o)
    assert sorted(s["id"] for s in SUP.exporter("perso")["series"]) == ["s-brute", "s-pub", "s-sans"]
    assert [s["id"] for s in SUP.exporter("marina")["series"]] == ["s-marina"]
