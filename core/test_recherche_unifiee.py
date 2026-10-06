"""S241 — recherche unifiée du Cœur : fan-out, délais, fusion, identité.

$ cd core && python3 -m pytest test_recherche_unifiee.py -v
"""
import asyncio
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import httpx  # noqa: E402
import pytest  # noqa: E402

import contexte_tenant  # noqa: E402
import recherche_unifiee as ru  # noqa: E402


@pytest.fixture(autouse=True)
def _bases(monkeypatch):
    monkeypatch.setattr(ru.orchestrateur, "_brique_base", lambda registre, nom: f"http://{nom}")


def _reponses(pannes=(), lents=(), forge_identite="service", espaces_en_panne=(), forge_mode="hybride"):
    vus = []

    async def gerer(requete: httpx.Request):
        hote = requete.url.host
        vus.append(requete)
        if hote in lents:
            await asyncio.sleep(1)
        if hote in pannes:
            raise httpx.ConnectError("hors ligne", request=requete)
        if hote == "forge":
            return httpx.Response(200, json={"mode": forge_mode, "identite": forge_identite, "resultats": [
                {"id": "f1", "source": "document", "titre": "Devis toiture", "extrait": "…", "exact": False},
                {"id": "k1", "source": "kb", "titre": "Procédure", "extrait": "…", "exact": False}]})
        if hote == "ingestion":
            return httpx.Response(200, json={"mode": "plein_texte", "resultats": [
                {"id": "i1", "source": "ingestion", "titre": "FAC-1", "extrait": "…", "exact": True}]})
        espace = requete.url.params["espace"]
        if espace in espaces_en_panne:
            raise httpx.ConnectError("espace hors ligne", request=requete)
        return httpx.Response(200, json={"mode": "hybride", "souvenirs": [
            {"id": f"m-{espace}", "titre": f"Souvenir {espace}", "extrait": "…", "correspondance": "lexicale"}]})

    return httpx.MockTransport(gerer), vus


def _lancer(transport, **kw):
    return asyncio.run(ru.rechercher("toiture FAC-1", registre=None, transport=transport, **kw))


def test_fusion_exacts_devant_et_toutes_les_sources():
    transport, _ = _reponses()
    rep = _lancer(transport)
    assert rep["resultats"][0]["id"] == "i1" and rep["resultats"][0]["exact"] is True
    assert {r["source"] for r in rep["resultats"]} == {
        "forge-document", "forge-kb", "ingestion", "memoire-perso", "memoire-solution", "memoire-veille"}
    assert rep["sources_indisponibles"] == []
    assert rep["modes"]["ingestion"] == "plein_texte" and rep["modes"]["forge"] == "hybride"


def test_ingestion_plein_texte_et_forge_hybride_aucune_source_degradee():
    transport, _ = _reponses()
    rep = _lancer(transport)
    assert rep["recherche_par_le_sens_indisponible"] == []


def test_forge_lexical_signalee_ingestion_jamais():
    transport, _ = _reponses(forge_mode="lexical")
    rep = _lancer(transport)
    assert rep["recherche_par_le_sens_indisponible"] == ["forge"]


def test_memoire_lexical_signalee_par_espace():
    assert ru.degradees({"forge": "hybride", "ingestion": "plein_texte",
                         "memoire-perso": "lexical", "memoire-veille": "hybride"}) == ["memoire-perso"]


def test_partage_signale():
    transport, _ = _reponses(forge_identite="service")
    rep = _lancer(transport)
    par_source = {r["source"]: r["partage"] for r in rep["resultats"]}
    assert par_source["forge-document"] is True and par_source["ingestion"] is True
    assert par_source["memoire-perso"] is False
    transport, _ = _reponses(forge_identite="utilisateur")
    assert {r["partage"] for r in _lancer(transport)["resultats"] if r["source"].startswith("forge")} == {False}


def test_source_en_panne_signalee_les_autres_repondent():
    transport, _ = _reponses(pannes=("forge",))
    rep = _lancer(transport)
    assert rep["sources_indisponibles"] == ["forge"]
    assert rep["resultats"] and not any(r["source"].startswith("forge") for r in rep["resultats"])


def test_source_trop_lente_signalee(monkeypatch):
    monkeypatch.setattr(ru, "DELAI_SOURCE", 0.05)
    transport, _ = _reponses(lents=("ingestion",))
    assert _lancer(transport)["sources_indisponibles"] == ["ingestion"]


def test_toutes_en_panne_leve():
    transport, _ = _reponses(pannes=("forge", "ingestion", "memoire"))
    with pytest.raises(ru.ToutesSourcesIndisponibles) as exc:
        _lancer(transport)
    assert exc.value.args[0] == ["forge", "ingestion", "memoire"]


def test_un_seul_espace_memoire_en_panne_garde_son_nom():
    transport, _ = _reponses(espaces_en_panne=("perso",))
    rep = _lancer(transport)
    assert rep["sources_indisponibles"] == ["memoire-perso"]
    sources = {r["source"] for r in rep["resultats"]}
    assert {"memoire-solution", "memoire-veille", "ingestion"} <= sources


def test_source_inconnue_refusee():
    transport, _ = _reponses()
    with pytest.raises(ValueError, match="source inconnue : bar, foo"):
        _lancer(transport, sources={"foo", "bar", "forge"})
    assert _lancer(transport, sources=set())["sources_indisponibles"] == []


def test_filtre_sources_et_requete_vide():
    transport, vus = _reponses()
    rep = _lancer(transport, sources={"memoire"})
    assert {r.url.host for r in vus} == {"memoire"}
    assert all(r["source"].startswith("memoire") for r in rep["resultats"])
    assert asyncio.run(ru.rechercher("  ", registre=None, transport=transport)) == {
        "resultats": [], "modes": {}, "sources_indisponibles": [],
        "recherche_par_le_sens_indisponible": []}


def test_identite_transmise(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-memoire")
    transport, vus = _reponses()

    async def scenario():
        contexte_tenant.definir_contexte(utilisateur="marina", user_token="JWT-M")
        return await ru.rechercher("toiture", registre=None, transport=transport)

    asyncio.run(scenario())
    forge = next(r for r in vus if r.url.host == "forge")
    memoire = [r for r in vus if r.url.host == "memoire"]
    assert forge.headers["X-Forge-User-Token"] == "Bearer JWT-M"
    assert {r.headers["X-User-Id"] for r in memoire} == {"marina"}
    assert {r.url.params["espace"] for r in memoire} == {"perso", "solution", "veille"}
