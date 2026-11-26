import pytest

import retention_registre as rr


def paquets(nom, n, debut=1):
    """n versions v<debut>.. + latest, `created_at` croissant avec le numéro."""
    r = [{"name": nom, "version": f"v{i}", "created_at": f"2026-11-{i:02d}T00:00:00Z"}
         for i in range(debut, debut + n)]
    r.append({"name": nom, "version": "latest", "created_at": "2026-11-30T00:00:00Z"})
    return r


class FauxForgejo:
    def __init__(self, liste):
        self.liste, self.appels, self.pannes = liste, [], set()

    def __call__(self, methode, chemin, jeton):
        self.appels.append((methode, chemin, jeton))
        if methode == "GET":
            page = int(chemin.split("page=")[1].split("&")[0]) if "page=" in chemin else 1
            return 200, (self.liste if page == 1 else [])
        version = chemin.rsplit("/", 1)[1]
        if version in self.pannes:
            return 500, None
        self.liste[:] = [p for p in self.liste if p["version"] != version]
        return 204, None

    def suppressions(self):
        return [c for m, c, _ in self.appels if m == "DELETE"]


CFG = {"URL": "http://f:3001", "TOKEN": "TOK", "OWNER": "wp-admin",
       "PREFIXES": ["calendrier-familial"], "GARDER": 10, "APPLIQUER": False}


def test_a_blanc_par_defaut_ne_supprime_rien_mais_liste():
    f = FauxForgejo(paquets("calendrier-familial-abc", 14))
    res = rr.appliquer_retention(f, CFG)
    assert f.suppressions() == []
    assert res["appliquee"] is False
    assert res["a_supprimer"] == [f"calendrier-familial-abc:v{i}" for i in (1, 2, 3, 4)]


def test_applique_garde_les_10_dernieres_et_jamais_latest():
    f = FauxForgejo(paquets("calendrier-familial-abc", 14))
    res = rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))
    restantes = {p["version"] for p in f.liste}
    assert restantes == {f"v{i}" for i in range(5, 15)} | {"latest"}
    assert res["supprimees"] == [f"calendrier-familial-abc:v{i}" for i in (1, 2, 3, 4)]
    assert all(c.endswith(("/v1", "/v2", "/v3", "/v4")) for c in f.suppressions())


def test_chaque_paquet_est_traite_separement_jumeau_compris():
    f = FauxForgejo(paquets("calendrier-familial-abc", 12) + paquets("calendrier-familial-jumeau-xyz", 3))
    res = rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))
    assert res["supprimees"] == ["calendrier-familial-abc:v1", "calendrier-familial-abc:v2"]


def test_paquet_hors_prefixes_jamais_touche():
    f = FauxForgejo(paquets("autre-app", 30) + paquets("calendrier-familial-abc", 11))
    res = rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))
    assert res["supprimees"] == ["calendrier-familial-abc:v1"]
    assert all("autre-app" not in c for c in f.suppressions())


def test_prefixe_doit_etre_une_frontiere_de_nom():
    # `calendrier-familial2-…` ne doit pas être pris pour `calendrier-familial-…`
    f = FauxForgejo(paquets("calendrier-familial2-abc", 30))
    assert rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))["supprimees"] == []


def test_refuse_de_garder_moins_de_3_versions():
    with pytest.raises(rr.ErreurRetention):
        rr.appliquer_retention(FauxForgejo(paquets("calendrier-familial-abc", 5)),
                               dict(CFG, GARDER=2, APPLIQUER=True))


def test_prefixes_vides_refuses():
    with pytest.raises(rr.ErreurRetention):
        rr.appliquer_retention(FauxForgejo([]), dict(CFG, PREFIXES=[]))


def test_echec_de_suppression_signale_partielle_et_continue():
    f = FauxForgejo(paquets("calendrier-familial-abc", 13))
    f.pannes = {"v1"}
    res = rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))
    assert res["echecs"] == ["calendrier-familial-abc:v1"]
    assert res["supprimees"] == ["calendrier-familial-abc:v2", "calendrier-familial-abc:v3"]


def test_listage_en_echec_ne_supprime_rien():
    def casse(m, c, j):
        return 500, None
    with pytest.raises(rr.ErreurRetention):
        rr.appliquer_retention(casse, dict(CFG, APPLIQUER=True))


def test_jeton_envoye_et_nom_encode():
    f = FauxForgejo(paquets("calendrier-familial-abc", 11))
    rr.appliquer_retention(f, dict(CFG, APPLIQUER=True))
    assert {j for _, _, j in f.appels} == {"TOK"}
    assert f.suppressions() == ["/api/v1/packages/wp-admin/container/calendrier-familial-abc/v1"]


def test_charger_config_defauts_sures():
    cfg = rr.charger_config({"EXECUTEUR_FORGEJO_REGISTRY_TOKEN": "t",
                             "EXECUTEUR_RETENTION_PREFIXES": "a-b, c"})
    assert cfg["APPLIQUER"] is False and cfg["GARDER"] == 10 and cfg["OWNER"] == "wp-admin"
    assert cfg["PREFIXES"] == ["a-b", "c"] and cfg["URL"] == "http://127.0.0.1:3001"
    with pytest.raises(rr.ErreurRetention):
        rr.charger_config({"EXECUTEUR_RETENTION_PREFIXES": "a"})  # jeton manquant
    with pytest.raises(rr.ErreurRetention):
        rr.charger_config({"EXECUTEUR_FORGEJO_REGISTRY_TOKEN": "t",
                           "EXECUTEUR_RETENTION_PREFIXES": "a", "EXECUTEUR_RETENTION_GARDER": "x"})
    assert rr.charger_config({"EXECUTEUR_FORGEJO_REGISTRY_TOKEN": "t",
                              "EXECUTEUR_RETENTION_PREFIXES": "a",
                              "EXECUTEUR_RETENTION_APPLIQUER": "1"})["APPLIQUER"] is True
