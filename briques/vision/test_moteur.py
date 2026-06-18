"""Tests — orchestrateur OCR : cascade, forçage, et repli HONNÊTE (jamais de faux texte)."""
import asyncio

import fournisseurs
import moteur


def _run(coro):
    return asyncio.run(coro)


class _FauxMoteur:
    """Moteur OCR factice : extrait un texte fixe, ou lève, ou rend vide — au choix."""
    def __init__(self, nom, texte=None, erreur=None):
        self.nom, self._texte, self._erreur = nom, texte, erreur

    def disponible(self):
        return True

    async def extraire(self, data, nom_fichier, mime):
        if self._erreur:
            raise RuntimeError(self._erreur)
        return self._texte


def _injecter(monkeypatch, *moteurs):
    """Remplace le registre + l'ordre par des moteurs factices (cascade contrôlée)."""
    reg = {m.nom: m for m in moteurs}
    monkeypatch.setattr(fournisseurs, "REGISTRE", reg)
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: list(reg))


# ── Repli honnête ────────────────────────────────────────────────────────────────
def test_aucun_moteur_donne_un_repli_honnete():
    d = _run(moteur.extraire(b"des octets", "f.pdf", "application/pdf"))
    assert d["place_holder"] is True
    assert d["texte"] == ""
    assert "Aucun moteur OCR configuré" in d["note"]


def test_contenu_vide_repli_sans_appeler_de_moteur():
    d = _run(moteur.extraire(b"", "f.png", "image/png"))
    assert d["place_holder"] is True and d["nb_caracteres"] == 0


def test_fournisseur_force_inconnu_donne_repli():
    d = _run(moteur.extraire(b"x", "f.png", "image/png", fournisseur="nexistepas"))
    assert d["place_holder"] is True
    assert "indisponible" in d["note"]


# ── Cascade ──────────────────────────────────────────────────────────────────────
def test_premier_moteur_qui_rend_du_texte_gagne(monkeypatch):
    _injecter(monkeypatch, _FauxMoteur("a", texte="Texte A"), _FauxMoteur("b", texte="Texte B"))
    d = _run(moteur.extraire(b"x", "f.pdf", "application/pdf"))
    assert d["backend"] == "a" and d["texte"] == "Texte A"
    assert d["place_holder"] is False and d["nb_caracteres"] == len("Texte A")


def test_cascade_replie_sur_le_suivant_si_le_premier_echoue(monkeypatch):
    _injecter(monkeypatch, _FauxMoteur("a", erreur="boom"), _FauxMoteur("b", texte="depuis B"))
    d = _run(moteur.extraire(b"x", "f.png", "image/png"))
    assert d["backend"] == "b" and d["texte"] == "depuis B"


def test_texte_vide_compte_comme_echec_et_passe_au_suivant(monkeypatch):
    _injecter(monkeypatch, _FauxMoteur("a", texte="   "), _FauxMoteur("b", texte="vrai"))
    d = _run(moteur.extraire(b"x", "f.png", "image/png"))
    assert d["backend"] == "b" and d["texte"] == "vrai"


def test_tous_echouent_repli_honnete_avec_erreurs(monkeypatch):
    _injecter(monkeypatch, _FauxMoteur("a", erreur="boom"), _FauxMoteur("b", texte=None))
    d = _run(moteur.extraire(b"x", "f.pdf", "application/pdf"))
    assert d["place_holder"] is True and d["texte"] == ""
    assert "a" in d["erreurs"] and "b" in d["erreurs"]
