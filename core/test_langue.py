"""Jarvis multilingue (S39) — aucun réseau, aucun LLM : on n'inspecte que les prompts
construits et la persistance de la préférence.

Écrit à l'origine en assertions au NIVEAU MODULE (`$ cd core && python3 test_langue.py`).
Cas plus sournois que les scripts `def run()` : pytest importe bien le fichier, donc les
assertions tournaient — mais le module déclarait **0 test**, un échec sortait en *erreur de
collecte* plutôt qu'en test rouge nommé, et une assertion précoce masquait toutes les
suivantes. Converti en tests pytest le 2026-07-28 ; les 24 assertions sont conservées.
"""
import os
import sys
import tempfile

# Isole la config et fournit le secret requis AVANT les imports du Cœur.
_tmp = tempfile.mkdtemp()
os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(_tmp, "assistant_config.json")
os.environ.setdefault("GATEWAY_KEY", "test-cle")
sys.path.insert(0, os.path.dirname(__file__))

import assistant          # noqa: E402
import briefing           # noqa: E402
import classer            # noqa: E402
import config_assistant   # noqa: E402
import langue             # noqa: E402
import summarisation      # noqa: E402

import pytest             # noqa: E402


# ── 1. Socle : normalisation + repli `fr` ────────────────────────────────────

@pytest.mark.parametrize("entree,attendu", [
    ("EN", "en"),      # casse ignorée
    ("es-ES", "es"),   # préfixe pris
    ("", "fr"),        # vide → repli
    (None, "fr"),      # None → repli
    ("zz", "fr"),      # inconnue → repli
])
def test_normalisation_et_repli(entree, attendu):
    assert langue.normaliser(entree) == attendu


# ── 2. Directives de langue (réponse + résumé) ───────────────────────────────

@pytest.mark.parametrize("code,mot", [("fr", "français"), ("en", "English"), ("es", "Español")])
def test_la_consigne_de_reponse_nomme_la_langue(code, mot):
    assert mot in langue.consigne_reponse(code)


def test_la_consigne_de_resume_est_correcte_en_anglais():
    assert langue.consigne_resume("en") == "en anglais (English)"


def test_une_langue_inconnue_dans_une_consigne_replie_sur_le_francais():
    consigne = langue.consigne_reponse("zz")
    assert "inconnu" not in consigne and "français" in consigne


# ── 3. Voix : locales BCP-47 + catalogue ─────────────────────────────────────

@pytest.mark.parametrize("code,locale", [
    ("fr", "fr-FR"), ("en", "en-US"), ("es", "es-ES"), ("zz", "fr-FR"),
])
def test_locale_voix(code, locale):
    assert langue.locale_voix(code) == locale


def test_le_catalogue_expose_les_trois_langues_completes():
    cat = langue.catalogue()
    assert len(cat) == 3 and {c["code"] for c in cat} == {"fr", "en", "es"}
    assert all({"code", "label", "locale_voix"} <= set(c) for c in cat)


# ── 4. Préférence persistée (config_assistant) ───────────────────────────────

def test_la_preference_de_langue_est_persistee_et_normalisee(tmp_path, monkeypatch):
    """Config isolée par test : l'original écrivait dans un dossier partagé et laissait
    la préférence sur 'es' pour les assertions suivantes — dépendance d'ordre cachée."""
    # `CONFIG_PATH` est un `Path` lu UNE fois à l'import : le poser en `str` casserait
    # `charger()` sur un `AttributeError` — piège payé en écrivant ce test.
    monkeypatch.setattr(config_assistant, "CONFIG_PATH", tmp_path / "assistant_config.json")
    assert config_assistant.charger()["langue"] == "fr", "défaut = fr"
    config_assistant.definir_langue("en")
    assert config_assistant.charger()["langue"] == "en"
    config_assistant.definir_langue("zz")
    assert config_assistant.charger()["langue"] == "fr", "inconnue normalisée à l'écriture"


# ── 5. Les 5 surfaces du Jarvis suivent la langue ────────────────────────────

def test_le_prompt_assistant_n_impose_plus_le_francais_en_dur():
    assert "toujours en français" not in assistant.PROMPT_SYSTEME


def test_le_briefing_suit_la_langue():
    assert "anglais (English)" in briefing.prompt_briefing("en")
    assert "français" in briefing.prompt_briefing("fr"), "non-régression du défaut"


def test_le_resume_suit_la_langue():
    assert "espagnol (Español)" in summarisation._prompt("es")


def test_le_classement_suit_la_langue_sans_traduire_les_cles():
    assert "anglais (English)" in classer._prompt("en")
    assert "compte_rendu" in classer._prompt("en"), \
        "les catégories sont des clés structurelles : elles ne se traduisent pas"
    assert "en français" in classer._prompt("fr"), "non-régression du défaut"
