"""S54 — tests de la migration des séries Oria → brique studio (hors Oria, sans I/O réseau)."""
import json
import os

import migrer


def _ecrire(dossier, nom, contenu):
    chemin = os.path.join(dossier, nom)
    with open(chemin, "w", encoding="utf-8") as f:
        if isinstance(contenu, str):
            f.write(contenu)
        else:
            json.dump(contenu, f, ensure_ascii=False)
    return chemin


def _serie_oria(sid="oria-1", titre="Saga", legacy=True):
    """Série au format atelier_router Oria. `legacy` = sans hiérarchie cycles/tomes."""
    s = {
        "id": sid,
        "world_id": "w1",
        "titre": titre,
        "cible": None,
        "langue": "fr",
        "bible": {"genre": "SF"},
        "personnages": [],
        "episodes": [{"n": 1, "titre": "Pilote", "texte": "..."}],
        "cree_par": "u1",
        "cree_le": "2026-06-10T00:00:00+00:00",
    }
    if not legacy:
        s["cycles"] = [{"id": "c1", "numero": 1, "titre": "Cycle 1", "resume": "",
                        "tomes": [{"id": "t1", "numero": 1, "titre": "Tome 1", "resume": ""}]}]
        s["tome_actif"] = "t1"
    return s


def test_import_frais_normalise(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    _ecrire(str(src), "oria-1.json", _serie_oria(legacy=True))

    r = migrer.importer_depuis(str(src), str(dest))

    assert r["importees"] == ["oria-1"]
    assert r["ignorees"] == [] and r["erreurs"] == []
    fichier = dest / "oria-1.json"
    assert fichier.exists()
    migree = json.loads(fichier.read_text(encoding="utf-8"))
    # _normaliser a reconstruit la hiérarchie d'une vieille série
    assert migree["cycles"] and migree["cycles"][0]["tomes"]
    assert migree["episodes"][0]["tome_id"] == migree["cycles"][0]["tomes"][0]["id"]
    assert migree["world_id"] == "w1"   # métadonnée conservée


def test_idempotent_ignore_si_deja_present(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    _ecrire(str(src), "oria-1.json", _serie_oria())

    migrer.importer_depuis(str(src), str(dest))
    r2 = migrer.importer_depuis(str(src), str(dest))

    assert r2["importees"] == []
    assert r2["ignorees"] == ["oria-1"]


def test_non_destructif_sans_ecraser(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    _ecrire(str(src), "oria-1.json", _serie_oria(titre="Ancien"))
    migrer.importer_depuis(str(src), str(dest))
    # la brique a retravaillé la série localement
    cible = dest / "oria-1.json"
    travail = json.loads(cible.read_text(encoding="utf-8"))
    travail["titre"] = "Travail de la brique"
    cible.write_text(json.dumps(travail, ensure_ascii=False), encoding="utf-8")

    # ré-importer NE doit pas écraser le travail
    _ecrire(str(src), "oria-1.json", _serie_oria(titre="Nouveau"))
    migrer.importer_depuis(str(src), str(dest))
    assert json.loads(cible.read_text(encoding="utf-8"))["titre"] == "Travail de la brique"


def test_ecraser_reimporte(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    _ecrire(str(src), "oria-1.json", _serie_oria(titre="V1"))
    migrer.importer_depuis(str(src), str(dest))

    _ecrire(str(src), "oria-1.json", _serie_oria(titre="V2"))
    r = migrer.importer_depuis(str(src), str(dest), ecraser=True)

    assert r["importees"] == ["oria-1"]
    cible = dest / "oria-1.json"
    assert json.loads(cible.read_text(encoding="utf-8"))["titre"] == "V2"


def test_ignore_non_json_et_signale_erreurs(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dest = tmp_path / "dest"; dest.mkdir()
    _ecrire(str(src), "valide.json", _serie_oria(sid="ok"))
    _ecrire(str(src), "note.txt", "pas du json")           # ignoré (extension)
    _ecrire(str(src), "casse.json", "{ pas du json")        # erreur JSON
    _ecrire(str(src), "sans-id.json", {"titre": "orpheline"})  # erreur : pas d'id

    r = migrer.importer_depuis(str(src), str(dest))

    assert r["importees"] == ["ok"]
    fichiers_en_erreur = {e["fichier"] for e in r["erreurs"]}
    assert fichiers_en_erreur == {"casse.json", "sans-id.json"}
    assert not (dest / "note.txt").exists()


def test_source_introuvable(tmp_path):
    dest = tmp_path / "dest"; dest.mkdir()
    r = migrer.importer_depuis(str(tmp_path / "nexiste-pas"), str(dest))
    assert r["importees"] == [] and len(r["erreurs"]) == 1


def test_main_sans_argument_renvoie_2():
    assert migrer.main([]) == 2


def test_main_migre_et_renvoie_0(tmp_path, capsys):
    src = tmp_path / "src"; src.mkdir()
    _ecrire(str(src), "oria-1.json", _serie_oria())
    dest = tmp_path / "dest"; dest.mkdir()

    code = migrer.importer_depuis(str(src), str(dest))
    assert code["erreurs"] == []
    # main() écrit dans STUDIO_DIR par défaut ; on vérifie juste le contrat de code retour
    assert migrer.main([str(src)]) == 0
    sortie = capsys.readouterr().out
    assert "importées" in sortie
