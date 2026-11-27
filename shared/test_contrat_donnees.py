import io
import json
import tarfile

import pytest

from shared import contrat_donnees as C

CLE = b"cle-de-test"
OBJETS = {"series": [{"id": "s1", "cree_par": "claire"}], "profils": []}


def _paquet(**kw):
    args = dict(app="studio", utilisateur="claire", version_schema="2", objets=OBJETS, cle=CLE)
    args.update(kw)
    return C.construire_paquet(**args)


def _tar(membres: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, contenu in membres.items():
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            t.addfile(info, io.BytesIO(contenu))
    return buf.getvalue()


def _membres(octets: bytes) -> dict:
    with tarfile.open(fileobj=io.BytesIO(octets), mode="r:gz") as t:
        return {m.name: t.extractfile(m).read() for m in t.getmembers()}


def _raison(octets, **kw):
    args = dict(cle=CLE, app="studio", utilisateur="claire", version_schema_app="2")
    args.update(kw)
    with pytest.raises(C.PaquetInvalide) as e:
        C.lire_paquet(octets, **args)
    return e.value.raison


def test_aller_retour():
    meta, objets = C.lire_paquet(_paquet(), CLE, "studio", "claire", "2")
    assert objets == OBJETS
    assert meta["comptages"] == {"profils": 0, "series": 1}
    assert meta["empreinte"] == C.empreinte(OBJETS)
    assert meta["version_schema"] == "2" and meta["utilisateur"] == "claire"


def test_empreinte_ne_depend_pas_de_l_ordre_des_cles():
    assert C.empreinte({"a": 1, "b": 2}) == C.empreinte({"b": 2, "a": 1})


def test_mauvaise_cle_refusee():
    assert _raison(_paquet(), cle=b"autre") == "signature"


def test_autre_utilisateur_refuse():
    assert _raison(_paquet(), utilisateur="marina") == "utilisateur"


def test_autre_app_refusee():
    assert _raison(_paquet(app="agenda")) == "app"


def test_version_future_refusee():
    assert _raison(_paquet(version_schema="3")) == "version_future"


def test_version_inferieure_acceptee_et_signalee():
    meta, _ = C.lire_paquet(_paquet(version_schema="1"), CLE, "studio", "claire", "2")
    assert meta["version_schema"] == "1"


def test_donnees_falsifiees_somme_de_controle():
    m = _membres(_paquet())
    m["donnees.json"] = json.dumps({"series": [], "profils": []}).encode()
    assert _raison(_tar(m)) == "somme_controle"


def test_meta_falsifiee_signature():
    m = _membres(_paquet())
    meta = json.loads(m["meta.json"])
    meta["utilisateur"] = "marina"
    m["meta.json"] = json.dumps(meta).encode()
    assert _raison(_tar(m), utilisateur="marina") == "signature"


def test_pas_une_archive():
    assert _raison(b"pas une archive") == "illisible"


def test_membre_inattendu_refuse():
    m = _membres(_paquet())
    m["../evil"] = b"x"
    assert _raison(_tar(m)) == "illisible"


def test_membre_manquant_refuse():
    m = _membres(_paquet())
    del m["donnees.json"]
    assert _raison(_tar(m)) == "illisible"


def test_octets_trop_gros(monkeypatch):
    monkeypatch.setattr(C, "TAILLE_MAX", 10)
    assert _raison(_paquet()) == "trop_gros"


def test_bloc_contrat_conforme():
    bloc = {"version_schema": "3",
            "exporter": {"methode": "POST", "chemin": "/support/exporter"},
            "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
            "importer": {"methode": "POST", "chemin": "/support/importer"}}
    assert C.valider_bloc_contrat(bloc) == []


@pytest.mark.parametrize("bloc", [
    None, {}, {"version_schema": "x"},
    {"version_schema": "1", "exporter": {"methode": "GET", "chemin": "/support/exporter"},
     "reinitialiser": {"methode": "POST", "chemin": "/support/r"},
     "importer": {"methode": "POST", "chemin": "/support/i"}},
    {"version_schema": "1", "exporter": {"methode": "POST", "chemin": "/public/exporter"},
     "reinitialiser": {"methode": "POST", "chemin": "/support/r"},
     "importer": {"methode": "POST", "chemin": "/support/i"}},
])
def test_bloc_contrat_non_conforme(bloc):
    assert C.valider_bloc_contrat(bloc) != []
