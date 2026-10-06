import pytest

from tests.outils_embedder import activer_embedder_factice

pytestmark = pytest.mark.asyncio


async def _creer(client, headers, space_id, titre, contenu="", type_="input"):
    r = await client.post(f"/api/v1/spaces/{space_id}/nodes",
                          json={"type": type_, "title": titre, "content_md": contenu}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _chercher(client, headers, space_id, q, **params):
    r = await client.get(f"/api/v1/spaces/{space_id}/search", params={"q": q, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.headers["X-Memoire-Mode"], r.json()


class TestRecherche:
    async def test_reference_exacte_en_tete(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        contenu = await _creer(client, auth_headers, sid, "Compte rendu", "Sprint S237b terminé")
        titre = await _creer(client, auth_headers, sid, "S237b résultats")
        await _creer(client, auth_headers, sid, "Plan S237", "S237 seulement")
        mode, res = await _chercher(client, auth_headers, sid, "S237b")
        assert mode == "hybride"
        assert [r["id"] for r in res[:2]] == [titre, contenu]
        assert {r["correspondance"] for r in res[:2]} == {"exacte"}

    async def test_embedder_en_panne_reste_utilisable(self, client, auth_headers, test_space):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Réunion budget", "factures fournisseurs")
        mode, res = await _chercher(client, auth_headers, sid, "reunion")
        assert mode == "lexical"
        assert [r["id"] for r in res] == [nid]
        assert res[0]["correspondance"] == "lexicale"

    async def test_souvenir_sans_vecteur_trouve_en_hybride(self, client, auth_headers, test_space, monkeypatch):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Contrat Durand", "signé")  # embedder en panne
        activer_embedder_factice(monkeypatch)
        mode, res = await _chercher(client, auth_headers, sid, "durand")
        assert mode == "hybride"
        assert nid in [r["id"] for r in res]

    async def test_proximite_de_sens(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Achat voiture")
        _, res = await _chercher(client, auth_headers, sid, "automobile")
        assert [r["id"] for r in res] == [nid]
        assert res[0]["correspondance"] == "vectorielle"

    async def test_requete_de_mots_vides_ne_renvoie_rien(self, client, auth_headers, test_space, embedder_factice):
        """Sans référence ni mot significatif, la branche par le sens renverrait quand même ses
        voisins les plus proches : une requête vide de sens ne doit rien renvoyer (S242)."""
        sid = test_space["id"]
        await _creer(client, auth_headers, sid, "Le recrutement de la société des équipes", "le de des")
        mode, res = await _chercher(client, auth_headers, sid, "le de des")
        assert mode == "hybride" and res == []

    async def test_faute_de_frappe(self, client, auth_headers, test_space):
        sid = test_space["id"]
        nid = await _creer(client, auth_headers, sid, "Fournisseurs", "Les factures du trimestre")
        _, res = await _chercher(client, auth_headers, sid, "facutre")
        assert [r["id"] for r in res] == [nid]

    async def test_filtre_type(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        projet = await _creer(client, auth_headers, sid, "Gamma", type_="projet")
        await _creer(client, auth_headers, sid, "Gamma", type_="input")
        _, res = await _chercher(client, auth_headers, sid, "gamma", type="projet")
        assert [r["id"] for r in res] == [projet]

    async def test_requete_vide(self, client, auth_headers, test_space):
        _, res = await _chercher(client, auth_headers, test_space["id"], "")
        assert res == []

    async def test_scores_decroissants(self, client, auth_headers, test_space, embedder_factice):
        sid = test_space["id"]
        for t in ("Delta un", "Delta deux", "Delta trois S-9"):
            await _creer(client, auth_headers, sid, t)
        _, res = await _chercher(client, auth_headers, sid, "delta S-9")
        scores = [r["score"] for r in res]
        assert scores == sorted(scores, reverse=True) and len(set(scores)) == len(scores)

    async def test_symboles_developpes_par_unaccent(self, client, auth_headers, test_space):
        """unaccent développe ⁇ en ??, … en ..., © en (C) : le motif ne doit pas devenir
        une expression régulière invalide (500)."""
        sid = test_space["id"]
        copyright_ = await _creer(client, auth_headers, sid, "Mentions", "Tous droits réservés ©2024")
        s1 = await _creer(client, auth_headers, sid, "Sprint S1 fini")
        for q in ("a1⁇⁇", "x⑴y2"):
            await _chercher(client, auth_headers, sid, q)
        _, res = await _chercher(client, auth_headers, sid, "©2024")
        assert res[0]["id"] == copyright_ and res[0]["correspondance"] == "exacte"
        _, res = await _chercher(client, auth_headers, sid, "S1…")
        assert res[0]["id"] == s1 and res[0]["correspondance"] == "exacte"

    async def test_bascule_lexicale_journalisee(self, client, auth_headers, test_space, caplog):
        with caplog.at_level("WARNING", logger="app.services.search_service"):
            mode, _ = await _chercher(client, auth_headers, test_space["id"], "bonjour")
        assert mode == "lexical"
        assert any("lexical" in r.getMessage() for r in caplog.records)

    async def test_limite_zero_refusee(self, client, auth_headers, test_space):
        r = await client.get(f"/api/v1/spaces/{test_space['id']}/search",
                             params={"q": "x", "limit": 0}, headers=auth_headers)
        assert r.status_code == 422


class TestIsolation:
    @pytest.mark.parametrize("embedder", ["panne", "factice"])
    async def test_aucune_fuite_entre_utilisateurs(self, client, auth_headers, autres_headers, monkeypatch, embedder):
        if embedder == "factice":
            activer_embedder_factice(monkeypatch)
        a = (await client.post("/api/v1/spaces", json={"name": "A"}, headers=auth_headers)).json()["id"]
        b = (await client.post("/api/v1/spaces", json={"name": "B"}, headers=autres_headers)).json()["id"]
        mien = await _creer(client, auth_headers, a, "Dossier Zéphyr Z-42", "confidentiel")
        await _creer(client, autres_headers, b, "Dossier Zéphyr Z-42", "confidentiel")
        for q in ("zephyr", "Z-42", "zepyhr", '"dossier zéphyr"'):
            _, res = await _chercher(client, auth_headers, a, q)
            assert [r["id"] for r in res] == [mien], q
        r = await client.get(f"/api/v1/spaces/{b}/search", params={"q": "zephyr"}, headers=auth_headers)
        assert r.status_code in (403, 404)
