"""Tests — Studio multilingue (langue de travail + traduction au rendu), repris hors Oria (S51).

Fonctions pures de la brique : pas de DB ni de Gateway réelle. La traduction est testée
avec `_gateway_answer` monkeypatché (succès + replis honnêtes)."""
import asyncio

import studio as A


# ── Normalisation de la langue ───────────────────────────────────
def test_norm_langue_codes_connus():
    assert A._norm_langue("en") == "en"
    assert A._norm_langue("EN") == "en"
    assert A._norm_langue("es") == "es"
    assert A._norm_langue("ar") == "ar"


def test_norm_langue_troncature_et_repli():
    assert A._norm_langue("fr-FR") == "fr"      # BCP-47 → 2 lettres
    assert A._norm_langue("es_ES") == "es"
    assert A._norm_langue("zz") == "fr"          # inconnu → repli fr
    assert A._norm_langue("") == "fr"
    assert A._norm_langue(None) == "fr"


# ── Consigne de rédaction injectée dans les prompts ──────────────
def test_consigne_langue_defaut_francais():
    assert "français" in A._consigne_langue({})
    assert "français" in A._consigne_langue({"langue": None})


def test_consigne_langue_autres_langues():
    assert "anglais" in A._consigne_langue({"langue": "en"})
    assert "espagnol" in A._consigne_langue({"langue": "es"})
    assert "arabe" in A._consigne_langue({"langue": "ar"})
    # langue inconnue → repli fr (jamais d'erreur)
    assert "français" in A._consigne_langue({"langue": "zz"})


# ── Traduction au rendu (lot Gateway, repli honnête) ─────────────
def _run(coro):
    return asyncio.run(coro)


def test_traduire_liste_vide():
    out, ok = _run(A._traduire([], "anglais (English)"))
    assert ok is True and out == []


def test_traduire_succes(monkeypatch):
    async def fake_gw(url, model, systeme, tache):
        return '[{"i":0,"t":"Hello"},{"i":1,"t":"World"}]'
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._traduire(["Bonjour", "Monde"], "anglais (English)"))
    assert ok is True
    assert out == ["Hello", "World"]


def test_traduire_desordre_recolle_par_index(monkeypatch):
    async def fake_gw(*a):
        return '[{"i":1,"t":"World"},{"i":0,"t":"Hello"}]'  # ordre inversé
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._traduire(["Bonjour", "Monde"], "anglais"))
    assert ok is True and out == ["Hello", "World"]


def test_traduire_mauvaise_longueur_repli(monkeypatch):
    async def fake_gw(*a):
        return '[{"i":0,"t":"Hello"}]'  # 1 ligne pour 2 → incohérent
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._traduire(["Bonjour", "Monde"], "anglais"))
    assert ok is False and out == ["Bonjour", "Monde"]


def test_traduire_json_illisible_repli(monkeypatch):
    async def fake_gw(*a):
        return "Désolé, je ne peux pas faire ça."
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._traduire(["Bonjour"], "anglais"))
    assert ok is False and out == ["Bonjour"]


def test_traduire_gateway_injoignable_repli(monkeypatch):
    async def fake_gw(*a):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._traduire(["Bonjour"], "anglais"))
    assert ok is False and out == ["Bonjour"]
