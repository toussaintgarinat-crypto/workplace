import uuid

import pytest

from app import database as db_module
from app.models.node import IpCraStage, Node, NodeStatus, NodeType, StorageTier
from app.services.recherche_conditions import Filtres
from app.services.recherche_lexicale import (
    classement_plein_texte, classement_trigramme, correspondances_exactes,
)
from app.services.recherche_vectorielle import classement_vectoriel
from tests.outils_embedder import vecteur_factice

pytestmark = pytest.mark.asyncio


async def _souvenirs(space_id, *specs):
    """specs : (titre, contenu, options) → ids dans l'ordre."""
    async with db_module.async_session_factory() as db:
        nodes = []
        for titre, contenu, opts in specs:
            n = Node(space_id=space_id, type=opts.get("type", NodeType.input),
                     ipcra_stage=opts.get("etape", IpCraStage.input),
                     storage_tier=opts.get("tier", StorageTier.hot),
                     status=opts.get("status", NodeStatus.active),
                     title=titre, content_md=contenu,
                     embedding=vecteur_factice(f"{titre}\n{contenu}") if opts.get("vecteur", True) else None)
            db.add(n)
            nodes.append(n)
        await db.commit()
        return [n.id for n in nodes]


async def _deux_espaces(client, auth_headers):
    ids = []
    for nom in ("Espace A", "Espace B"):
        r = await client.post("/api/v1/spaces", json={"name": nom}, headers=auth_headers)
        ids.append(uuid.UUID(r.json()["id"]))
    return ids


class TestPleinTexte:
    async def test_accents_pluriels_et_sans_vecteur(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        reunion, factures = await _souvenirs(a, ("Réunion budget", "", {"vecteur": False}),
                                             ("Fournisseurs", "Les factures du trimestre", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "reunion", Filtres(a), 10) == [reunion]
            assert await classement_plein_texte(db, "facture", Filtres(a), 10) == [factures]

    async def test_titre_classe_avant_contenu(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        contenu, titre = await _souvenirs(a, ("Divers", "parle de Kubernetes", {}),
                                          ("Kubernetes", "notes", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "kubernetes", Filtres(a), 10) == [titre, contenu]

    async def test_mots_vides_ne_font_pas_remonter_un_titre(self, client, auth_headers):
        """Le titre est indexé en `simple` (mots vides compris) : « le », « de » de la requête
        ne doivent pas faire remonter un souvenir hors sujet dont le titre les contient."""
        a, _ = await _deux_espaces(client, auth_headers)
        hors_sujet, toit = await _souvenirs(
            a, ("Recrutement d'un conducteur de travaux", "Poste basé à Lyon.", {}),
            ("Devis toiture", "Refaire le toit de la maison Martin.", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "refaire le toit", Filtres(a), 10) == [toit]
            assert await classement_plein_texte(db, "le de des", Filtres(a), 10) == []

    async def test_operateurs_tsquery_ignores(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        await _souvenirs(a, ("Le", "de la", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "&|!:*", Filtres(a), 10) == []


class TestTrigramme:
    async def test_faute_de_frappe(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        (factures,) = await _souvenirs(a, ("Fournisseurs", "Les factures du trimestre", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "facutre", Filtres(a), 10) == []
            assert await classement_trigramme(db, "facutre", Filtres(a), 10) == [factures]
            assert await classement_trigramme(db, "automobile", Filtres(a), 10) == []

    async def test_mots_vides_ignores_par_le_filet(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        hors_sujet, factures = await _souvenirs(
            a, ("Le recrutement de la société des équipes", "", {}),
            ("Fournisseurs", "Les factures du trimestre", {}))
        async with db_module.async_session_factory() as db:
            assert await classement_trigramme(db, "le de des", Filtres(a), 10) == []
            assert await classement_trigramme(db, "les facutre", Filtres(a), 10) == [factures]


class TestExactes:
    async def test_mot_entier_titre_et_compte(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        contenu, titre, voisin, deux = await _souvenirs(
            a,
            ("Compte rendu", "Sprint S237b terminé", {}),
            ("S237b résultats", "", {}),
            ("Plan", "Sprint S237 seulement", {}),
            ("Bilan", "S237b et INV-2026-042", {}),
        )
        async with db_module.async_session_factory() as db:
            r = await correspondances_exactes(db, ["S237b", "INV-2026-042"], Filtres(a), 10)
        assert voisin not in r
        assert r[deux].references_trouvees == 2
        assert r[titre].dans_titre and not r[contenu].dans_titre

    async def test_expression_et_accents(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        (n,) = await _souvenirs(a, ("Note", "la Réunion\n  Budget de mars", {}))
        async with db_module.async_session_factory() as db:
            r = await correspondances_exactes(db, ["reunion budget"], Filtres(a), 10)
        assert n in r


class TestVectoriel:
    async def test_synonyme_et_plancher(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        voiture, autre = await _souvenirs(a, ("Achat voiture", "", {}), ("Recette", "gâteau", {}))
        async with db_module.async_session_factory() as db:
            r = await classement_vectoriel(db, vecteur_factice("automobile"), Filtres(a), 10)
        assert r == [voiture]


class TestIsolationEtFiltres:
    async def test_aucune_branche_ne_sort_de_l_espace(self, client, auth_headers):
        a, b = await _deux_espaces(client, auth_headers)
        (dans_a,) = await _souvenirs(a, ("Projet Zéphyr Z-42", "", {}))
        await _souvenirs(b, ("Projet Zéphyr Z-42", "", {}))
        async with db_module.async_session_factory() as db:
            f = Filtres(a)
            assert await classement_plein_texte(db, "zephyr", f, 10) == [dans_a]
            assert await classement_trigramme(db, "zepyhr", f, 10) == [dans_a]
            assert list(await correspondances_exactes(db, ["Z-42"], f, 10)) == [dans_a]
            assert await classement_vectoriel(db, vecteur_factice("Projet Zéphyr Z-42"), f, 10) == [dans_a]

    async def test_filtres_et_statut(self, client, auth_headers):
        a, _ = await _deux_espaces(client, auth_headers)
        bon, mauvais_type, mauvais_tier, retire = await _souvenirs(
            a,
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.archive}),
            ("Alpha", "", {"type": NodeType.input, "etape": IpCraStage.projet, "tier": StorageTier.archive}),
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.hot}),
            ("Alpha", "", {"type": NodeType.projet, "etape": IpCraStage.projet, "tier": StorageTier.archive,
                           "status": NodeStatus.pending_removal}),
        )
        f = Filtres(a, type="projet", etape="projet", tier="archive")
        async with db_module.async_session_factory() as db:
            assert await classement_plein_texte(db, "alpha", f, 10) == [bon]
            assert list(await correspondances_exactes(db, ["Alpha"], f, 10)) == [bon]
            assert await classement_vectoriel(db, vecteur_factice("Alpha"), f, 10) == [bon]
