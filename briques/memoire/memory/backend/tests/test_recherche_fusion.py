import uuid

from app.services.recherche_fusion import (
    CorrespondanceExacte, extraire_references, fusion_rrf, motif_reference, ordonner,
)

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


class TestReferences:
    def test_code_avec_chiffre(self):
        assert extraire_references("bilan du S237b") == ["S237b"]

    def test_tirets_email_fichier(self):
        assert extraire_references("INV-2026-042 jean.dupont@exemple.fr docker-compose.yml.") == [
            "INV-2026-042", "jean.dupont@exemple.fr", "docker-compose.yml"]

    def test_guillemets(self):
        assert extraire_references('« réunion   budget » et "plan B" demain') == ["réunion budget", "plan B"]

    def test_mots_ordinaires_ignores(self):
        assert extraire_references("facture du garage") == []

    def test_doublons_insensibles_a_la_casse(self):
        assert extraire_references("S237b s237B") == ["S237b"]

    def test_ponctuation_seule_ignoree(self):
        assert extraire_references("a -- b") == []


class TestMotif:
    def test_echappe_et_borne(self):
        assert motif_reference("v1.2") == r"(^|[^[:alnum:]])v1\.2($|[^[:alnum:]])"

    def test_espaces_souples(self):
        assert motif_reference("réunion budget") == "(^|[^[:alnum:]])réunion[[:space:]]+budget($|[^[:alnum:]])"


class TestFusion:
    def test_rrf(self):
        s = fusion_rrf([[A, B], [B, C]])
        assert s[B] == 1 / 62 + 1 / 61  # fusion_rrf brute, sans epsilon de position
        assert s[B] > s[A] > s[C]

    def test_exacts_en_tete_meme_sans_fusion(self):
        r = ordonner({D: CorrespondanceExacte(1, False)}, [A, B], [B], limite=10)
        assert [c.id for c in r] == [D, B, A]
        assert [c.correspondance for c in r] == ["exacte", "les_deux", "lexicale"]

    def test_plus_de_references_avant_titre(self):
        r = ordonner({A: CorrespondanceExacte(1, True), B: CorrespondanceExacte(2, False)}, [], [], limite=10)
        assert [c.id for c in r] == [B, A]

    def test_titre_avant_contenu(self):
        r = ordonner({A: CorrespondanceExacte(1, False), B: CorrespondanceExacte(1, True)}, [], [], limite=10)
        assert [c.id for c in r] == [B, A]

    def test_vectorielle_seule_et_limite(self):
        r = ordonner({}, [A], [C], limite=1)
        assert len(r) == 1

    def test_scores_strictement_decroissants(self):
        r = ordonner({D: CorrespondanceExacte(1, False)}, [A, B, C], [C, B], limite=10)
        scores = [c.score for c in r]
        assert all(x > y for x, y in zip(scores, scores[1:]))
