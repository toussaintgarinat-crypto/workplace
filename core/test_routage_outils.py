"""Routage d'outils par embeddings — filtrer le contexte sur les outils pertinents.

Vérifie le cœur du sprint : on n'envoie au LLM que les `top_k` outils les plus proches de la
requête (similarité cosinus) PLUS un socle « toujours pertinent », avec des replis HONNÊTES
(routage inactif / non indexé / Gateway KO → on laisse passer TOUS les outils, comportement
actuel inchangé). Les embeddings sont MOCKÉS : un faux modèle déterministe (sac-de-mots sur un
petit vocabulaire) remplace l'appel Gateway — aucun réseau, reproductible.

Autonome (asyncio.run, faux client httpx) — motif du reste de core/.
    $ cd core && python3 test_routage_outils.py
"""
import asyncio

import routage_outils as r


# ── Faux modèle d'embedding : sac-de-mots sur un vocabulaire fixe ─────────────
# Chaque texte devient un vecteur multi-hot ; deux textes partageant des mots ont un
# cosinus élevé. Suffisant pour piloter le classement top_k de façon déterministe.
_VOCAB = ["calcul", "nombre", "additionne", "facture", "paiement", "agenda",
          "rendez", "vous", "mémoire", "note", "voix", "audio"]


def _vecteur(texte: str) -> list:
    t = texte.lower()
    return [float(t.count(mot)) for mot in _VOCAB]


async def _fake_embed_lot(client, textes):
    return [_vecteur(t) for t in textes]


def _spec(nom: str, desc: str) -> dict:
    return {"type": "function", "function": {"name": nom, "description": desc}}


def _outils():
    # 4 outils découverts, chacun ancré sur un thème distinct, + un socle « en dur ».
    return [
        _spec("additionner", "calcul : additionne des nombre"),
        _spec("relancer_factures", "facture impayée : relance de paiement"),
        _spec("prochain_rdv", "agenda : prochain rendez vous"),
        _spec("noter", "mémoire : prendre une note"),
        _spec("lister_entreprises", "socle interne en dur"),
    ]


def _indexer(specs):
    """Construit l'index avec le faux modèle, ACTIF forcé. Renvoie le succès."""
    r.ACTIF = True
    r._embed_lot = _fake_embed_lot
    return asyncio.run(r.indexer(specs, client=object()))


def _noms(specs):
    return [s["function"]["name"] for s in specs]


# ── Indexation au démarrage ──────────────────────────────────────────────────

def test_indexer_construit_lindex():
    try:
        assert _indexer(_outils()) is True
        assert r._pret is True
        assert set(r._index) == set(_noms(_outils()))      # un vecteur par outil
    finally:
        r.reinitialiser()


def test_indexer_inerte_si_desactive():
    r.reinitialiser()
    r.ACTIF = False
    r._embed_lot = _fake_embed_lot
    try:
        assert asyncio.run(r.indexer(_outils(), client=object())) is False
        assert r._pret is False and not r._index            # rien indexé → repli total
    finally:
        r.reinitialiser()


def test_indexer_repli_si_gateway_ko():
    r.reinitialiser()
    r.ACTIF = True

    async def _ko(client, textes):
        return None                                         # Gateway injoignable au démarrage

    r._embed_lot = _ko
    try:
        assert asyncio.run(r.indexer(_outils(), client=object())) is False
        assert r._pret is False
    finally:
        r.reinitialiser()


# ── Filtrage à la requête ────────────────────────────────────────────────────

def test_filtre_garde_le_pertinent_et_le_socle():
    try:
        _indexer(_outils())
        socle = {"lister_entreprises"}
        out = asyncio.run(r.filtrer_outils(
            "additionne ces nombre pour moi", _outils(),
            client=object(), top_k=1, toujours=socle))
        noms = set(_noms(out))
        assert "additionner" in noms          # le plus proche de la requête
        assert socle <= noms                  # le socle « en dur » est toujours là
        assert "relancer_factures" not in noms and "prochain_rdv" not in noms
    finally:
        r.reinitialiser()


def test_filtre_preserve_lordre_dorigine():
    try:
        _indexer(_outils())
        out = asyncio.run(r.filtrer_outils(
            "facture paiement agenda rendez vous note", _outils(),
            client=object(), top_k=8, toujours=set()))
        gardes = _noms(out)
        attendu = [n for n in _noms(_outils()) if n in gardes]
        assert gardes == attendu              # ordre d'entrée conservé → préfixe cacheable
    finally:
        r.reinitialiser()


def test_filtre_repli_total_si_non_pret():
    r.reinitialiser()                          # jamais indexé
    tous = _outils()
    out = asyncio.run(r.filtrer_outils("peu importe", tous, client=object()))
    assert out is tous                         # liste INCHANGÉE (comportement actuel)


def test_filtre_repli_si_embedding_requete_echoue():
    try:
        _indexer(_outils())

        async def _ko(client, textes):
            return None                        # la Gateway tombe au moment de la requête

        r._embed_lot = _ko
        tous = _outils()
        out = asyncio.run(r.filtrer_outils("additionne", tous, client=object()))
        assert out is tous                     # repli honnête : on laisse tout passer
    finally:
        r.reinitialiser()


def test_filtre_repli_sur_requete_vide():
    try:
        _indexer(_outils())
        tous = _outils()
        out = asyncio.run(r.filtrer_outils("   ", tous, client=object()))
        assert out is tous                     # rien à router → on ne filtre pas
    finally:
        r.reinitialiser()


def test_selectionner_est_pur_et_borne_au_top_k():
    # Cœur pur, sans Gateway : on pose l'index à la main et on vérifie le bornage.
    try:
        r.ACTIF = True
        r._index = {n: r._normaliser(_vecteur(d))
                    for n, d in [("additionner", "calcul nombre additionne"),
                                 ("relancer_factures", "facture paiement"),
                                 ("prochain_rdv", "agenda rendez vous")]}
        r._pret = True
        out = r.selectionner(_vecteur("calcul nombre"),
                             [_spec("additionner", ""), _spec("relancer_factures", ""),
                              _spec("prochain_rdv", "")],
                             top_k=1, toujours=set())
        assert _noms(out) == ["additionner"]   # un seul, le plus proche
    finally:
        r.reinitialiser()


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
