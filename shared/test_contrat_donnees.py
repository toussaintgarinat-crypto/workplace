import hashlib
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


def _tar_liste(membres: list) -> bytes:
    """Comme _tar, mais accepte des noms dupliqués : liste de (nom, contenu)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, contenu in membres:
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            t.addfile(info, io.BytesIO(contenu))
    return buf.getvalue()


def _meta_signee(donnees: bytes, **champs) -> bytes:
    """meta.json correctement signée avec CLE, champs surchargeables."""
    meta = {"format": C.FORMAT, "app": "studio", "utilisateur": "claire", "version_schema": "2",
            "cree_le": "2026-01-01T00:00:00+00:00", "comptages": {},
            "empreinte": hashlib.sha256(donnees).hexdigest()}
    meta.update(champs)
    meta["signature"] = C._signer(meta, CLE)
    return json.dumps(meta).encode()


DONNEES_VIDES = json.dumps({"series": [], "profils": []}).encode()


@pytest.mark.parametrize("signature", ["é", "\ud800"])
def test_signature_non_ascii_refusee(signature):
    m = _membres(_paquet())
    meta = json.loads(m["meta.json"])
    meta["signature"] = signature
    m["meta.json"] = json.dumps(meta).encode()
    assert _raison(_tar(m)) == "signature"


def test_meta_trop_imbriquee_illisible():
    m = _membres(_paquet())
    m["meta.json"] = b"[" * 1000000 + b"]" * 1000000
    assert _raison(_tar(m)) == "illisible"


def test_donnees_trop_imbriquees_illisible():
    donnees = b"[" * 1000000 + b"]" * 1000000
    octets = _tar_liste([("meta.json", _meta_signee(donnees)), ("donnees.json", donnees)])
    assert _raison(octets) == "illisible"


def test_meta_non_objet_illisible():
    m = _membres(_paquet())
    m["meta.json"] = b"[1, 2]"
    assert _raison(_tar(m)) == "illisible"


@pytest.mark.parametrize("version", ["abc", "٣", "²"])
def test_version_non_ascii_refusee(version):
    octets = _tar_liste([("meta.json", _meta_signee(DONNEES_VIDES, version_schema=version)),
                         ("donnees.json", DONNEES_VIDES)])
    assert _raison(octets) == "format"


def test_membre_duplique_illisible():
    octets = _tar_liste([("meta.json", _meta_signee(DONNEES_VIDES)),
                         ("meta.json", _meta_signee(DONNEES_VIDES)),
                         ("donnees.json", DONNEES_VIDES)])
    assert _raison(octets) == "illisible"


def test_membre_au_dessus_du_plafond_trop_gros(monkeypatch):
    # Données très compressibles : l'archive reste petite, mais le membre décompressé dépasse le plafond.
    objets = {"series": ["a" * 100000]}
    octets = _paquet(objets=objets)
    monkeypatch.setattr(C, "TAILLE_MAX", len(octets) + 10)
    assert _raison(octets) == "trop_gros"


@pytest.mark.parametrize("version", ["²", "٣"])
def test_bloc_version_non_ascii_refusee(version):
    bloc = {"version_schema": version,
            "exporter": {"methode": "POST", "chemin": "/support/exporter"},
            "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
            "importer": {"methode": "POST", "chemin": "/support/importer"}}
    assert C.valider_bloc_contrat(bloc) != []


def test_bloc_chemin_avec_segment_parent_refuse():
    bloc = {"version_schema": "1",
            "exporter": {"methode": "POST", "chemin": "/support/../public/exporter"},
            "reinitialiser": {"methode": "POST", "chemin": "/support/r"},
            "importer": {"methode": "POST", "chemin": "/support/i"}}
    assert C.valider_bloc_contrat(bloc) != []


def test_surrogate_dans_meta_refusee_signature():
    m = _membres(_paquet())
    meta = json.loads(m["meta.json"])
    meta["app"] = "\ud800"
    m["meta.json"] = json.dumps(meta).encode()
    assert _raison(_tar(m)) == "signature"


BLOC_OK = {"version_schema": "1",
           "exporter": {"methode": "POST", "chemin": "/support/exporter"},
           "reinitialiser": {"methode": "POST", "chemin": "/support/reinitialiser"},
           "importer": {"methode": "POST", "chemin": "/support/importer"}}


@pytest.mark.parametrize("chemin", [
    "/support/%2e%2e/x", "/support/%2E%2E/x", "/support/./x", "/support//x",
    "/support/a\\b", "/support/exporter/", "/support/a b", "/support/a?x=1", "/support/é",
    "/support/", "/supportx/exporter"])
def test_chemin_dangereux_refuse(chemin):
    assert C.chemin_support_sur(chemin) is False
    bloc = dict(BLOC_OK, exporter={"methode": "POST", "chemin": chemin})
    assert C.valider_bloc_contrat(bloc)


def test_chemins_sains_acceptes():
    for ch in ("/support/exporter", "/support/v1/exporter", "/support/a-b_c.d~e"):
        assert C.chemin_support_sur(ch) is True
    assert C.valider_bloc_contrat(BLOC_OK) == []
