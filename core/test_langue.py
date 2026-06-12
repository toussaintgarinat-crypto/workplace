"""Validation du Jarvis multilingue (Sprint S39).

Autonome : aucune dépendance pytest, aucun réseau ni LLM (on n'inspecte que les
prompts construits et la persistance de la préférence). Config isolée en dossier
temporaire.
    $ cd core && python3 test_langue.py
Sortie « ✅ TOUS LES TESTS PASSENT » = socle langue + repli `fr` + préférence
persistée + les 5 surfaces du Jarvis (chat/briefing/résumé/classement/voix)
rédigées dans la langue choisie, sans régression du français par défaut.
"""

import os
import sys
import tempfile

# Isole la config et fournit le secret requis AVANT les imports du Cœur.
_tmp = tempfile.mkdtemp()
os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(_tmp, "assistant_config.json")
os.environ.setdefault("GATEWAY_KEY", "test-cle")
sys.path.insert(0, os.path.dirname(__file__))

import langue              # noqa: E402
import config_assistant    # noqa: E402
import assistant           # noqa: E402
import briefing            # noqa: E402
import classer             # noqa: E402
import summarisation       # noqa: E402

_ok = 0


def vrai(cond, libelle):
    global _ok
    assert cond, "❌ " + libelle
    _ok += 1
    print("  ✅ " + libelle)


# ── 1. Socle : normalisation + repli `fr` ────────────────────────────────────
print("\n1. Socle langue (normalisation, repli)")
vrai(langue.normaliser("EN") == "en", "casse ignorée : 'EN' → 'en'")
vrai(langue.normaliser("es-ES") == "es", "préfixe pris : 'es-ES' → 'es'")
vrai(langue.normaliser("") == "fr", "vide → repli 'fr'")
vrai(langue.normaliser(None) == "fr", "None → repli 'fr'")
vrai(langue.normaliser("zz") == "fr", "langue inconnue → repli 'fr'")


# ── 2. Directives de langue (réponse + résumé) ───────────────────────────────
print("\n2. Directives de langue")
vrai("français" in langue.consigne_reponse("fr"), "consigne réponse fr cite « français »")
vrai("English" in langue.consigne_reponse("en"), "consigne réponse en cite « English »")
vrai("Español" in langue.consigne_reponse("es"), "consigne réponse es cite « Español »")
vrai(langue.consigne_resume("en") == "en anglais (English)", "consigne résumé en correcte")
vrai("inconnu" not in langue.consigne_reponse("zz") and "français" in langue.consigne_reponse("zz"),
     "langue inconnue dans une consigne → français (repli)")


# ── 3. Voix : locales BCP-47 + catalogue ─────────────────────────────────────
print("\n3. Voix (locales) + catalogue")
vrai(langue.locale_voix("fr") == "fr-FR", "locale voix fr → fr-FR")
vrai(langue.locale_voix("en") == "en-US", "locale voix en → en-US")
vrai(langue.locale_voix("es") == "es-ES", "locale voix es → es-ES")
vrai(langue.locale_voix("zz") == "fr-FR", "locale voix inconnue → fr-FR (repli)")
cat = langue.catalogue()
vrai(len(cat) == 3 and {c["code"] for c in cat} == {"fr", "en", "es"},
     "catalogue = 3 langues (fr/en/es)")
vrai(all({"code", "label", "locale_voix"} <= set(c) for c in cat),
     "chaque entrée du catalogue porte code/label/locale_voix")


# ── 4. Préférence persistée (config_assistant) ───────────────────────────────
print("\n4. Préférence persistée")
vrai(config_assistant.charger()["langue"] == "fr", "défaut = fr")
config_assistant.definir_langue("en")
vrai(config_assistant.charger()["langue"] == "en", "definir_langue('en') persisté et relu")
config_assistant.definir_langue("zz")
vrai(config_assistant.charger()["langue"] == "fr", "langue inconnue normalisée → fr à l'écriture")
config_assistant.definir_langue("es")  # on laisse 'es' pour les prompts ci-dessous


# ── 5. Les 5 surfaces du Jarvis suivent la langue ────────────────────────────
print("\n5. Surfaces du Jarvis paramétrées")
vrai("toujours en français" not in assistant.PROMPT_SYSTEME,
     "assistant : plus de « toujours en français » codé en dur")
vrai("anglais (English)" in briefing.prompt_briefing("en"),
     "briefing : prompt en anglais quand langue=en")
vrai("français" in briefing.prompt_briefing("fr"),
     "briefing : prompt en français par défaut (non-régression)")
vrai("espagnol (Español)" in summarisation._prompt("es"),
     "résumé : condensation en espagnol quand langue=es")
vrai("anglais (English)" in classer._prompt("en"),
     "classement : ligne resume en anglais quand langue=en")
vrai("compte_rendu" in classer._prompt("en"),
     "classement : catégories (clés structurelles) inchangées quel que soit la langue")
vrai("en français" in classer._prompt("fr"),
     "classement : resume en français par défaut (non-régression)")


print(f"\n✅ TOUS LES TESTS PASSENT ({_ok} assertions)")
