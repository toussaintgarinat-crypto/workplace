"""S241 — fonctions pures de la recherche Forge (aucune base)."""
from uuid import uuid4

from app.recherche_fusion import (
    CorrespondanceExacte, extraire_references, fusion_rrf, motif_reference, ordonner,
)


def test_extraire_references_codes_et_guillemets():
    refs = extraire_references('facture FAC-2026-0042 pour « contrat cadre », écrire à a@b.fr')
    assert refs == ["contrat cadre", "FAC-2026-0042", "a@b.fr"]


def test_extraire_references_ignore_les_mots_simples():
    assert extraire_references("devis toiture maison") == []


def test_motif_reference_echappe_et_limite_aux_mots():
    m = motif_reference("fac-2026.1")
    assert m == r"(^|[^[:alnum:]])fac-2026\.1($|[^[:alnum:]])"


def test_fusion_rrf_additionne_les_rangs():
    a, b = ("document", uuid4()), ("kb", uuid4())
    s = fusion_rrf([[a, b], [b]])
    assert s[b] > s[a]


def test_ordonner_exacts_devant_puis_rrf():
    exact, lex, vec = ("document", uuid4()), ("document", uuid4()), ("kb", uuid4())
    classes = ordonner({exact: CorrespondanceExacte(1, False)}, [lex, exact], [vec, lex], 10)
    assert [c.cle for c in classes] == [exact, lex, vec]
    assert [c.correspondance for c in classes] == ["exacte", "les_deux", "vectorielle"]
    assert all(classes[i].score > classes[i + 1].score for i in range(len(classes) - 1))


def test_ordonner_respecte_la_limite():
    cles = [("document", uuid4()) for _ in range(5)]
    assert len(ordonner({}, cles, [], 2)) == 2
    assert ordonner({}, cles, [], 0) == []


def test_extraire_references_guillemets_typographiques_anglais():
    # U+201C / U+201D ecrits en echappements pour qu'aucun outil ne les altere
    assert extraire_references("devis “contrat cadre” urgent") == ["contrat cadre"]
    assert extraire_references("voir “FAC-1”") == ["FAC-1"]
