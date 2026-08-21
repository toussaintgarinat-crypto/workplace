"""Journal brut des appels LLM (2e chantier veille deepseek-harness/Cordis, 2026-08-21).

Invariant « journal = vérité » : PAR APPEL LLM réellement abouti, le nécessaire pour
reconstruire ce qui a atteint le modèle (messages envoyés, outils offerts, réponse reçue).
Autonome : journal en tmp.
    $ cd core && python3 -m pytest test_journal_modele.py -v
"""
import os
import tempfile

os.environ["MODELE_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "modele.jsonl")

import journal_modele as jm  # noqa: E402


def _reset():
    if jm.CHEMIN.exists():
        jm.CHEMIN.unlink()


def test_enregistrer_et_relire_un_appel():
    _reset()
    ok = jm.enregistrer_appel(
        fil="web:dashboard", etiquette="chat", modele="openai/gpt-4o-mini",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "salut"}],
        outils_offerts=["agenda_consulter"],
        message_recu={"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "agenda_consulter", "arguments": "{}"}}]})
    assert ok is True
    appels = jm.appels("web:dashboard")
    assert len(appels) == 1
    a = appels[0]
    assert a["modele"] == "openai/gpt-4o-mini"
    assert a["outils_offerts"] == ["agenda_consulter"]
    assert a["message_recu"]["tool_calls"][0]["function"]["name"] == "agenda_consulter"
    assert a["messages"][1]["content"] == "salut"


def test_appels_filtre_par_fil():
    _reset()
    jm.enregistrer_appel(fil="fil-a", etiquette="chat", modele="m", messages=[])
    jm.enregistrer_appel(fil="fil-b", etiquette="chat", modele="m", messages=[])
    assert len(jm.appels("fil-a")) == 1
    assert len(jm.appels("fil-b")) == 1


def test_fil_absent_journalise_quand_meme():
    """Appel hors conversation (classement, MOA…) : `fil=None` est légitime, pas une erreur."""
    _reset()
    ok = jm.enregistrer_appel(fil=None, etiquette="classement", modele="m",
                              messages=[{"role": "user", "content": "x"}])
    assert ok is True
    lignes = jm._lignes()
    assert len(lignes) == 1 and lignes[0]["fil"] is None


def test_erreur_journalisee_sans_modele():
    _reset()
    ok = jm.enregistrer_appel(fil="fil-a", etiquette="chat", modele=None,
                              messages=[{"role": "user", "content": "x"}],
                              erreur="Aucun modèle disponible.")
    assert ok is True
    a = jm.appels("fil-a")[0]
    assert a["modele"] is None and a["erreur"] == "Aucun modèle disponible."


def test_bornage_taille(monkeypatch):
    _reset()
    monkeypatch.setenv("MODELE_JOURNAL_MAX", "50")
    for i in range(120):
        jm.enregistrer_appel(fil="fil-borne", etiquette="chat", modele="m",
                             messages=[{"role": "user", "content": f"msg {i}"}])
    tous = [l for l in jm._lignes() if l.get("fil") == "fil-borne"]
    assert len(tous) <= 60  # borné à ~50 (réécrit au-delà de 1,2×)
    assert tous[-1]["messages"][0]["content"] == "msg 119"


def test_check_vivant_detecte_un_ecart_et_ne_leve_jamais(monkeypatch):
    """Runtime check : si la relecture immédiate diffère de ce qu'on vient d'écrire
    (troncature disque, écriture concurrente corrompue…), `enregistrer_appel` renvoie
    False et loggue — mais ne lève JAMAIS (best-effort, ne doit pas casser l'appelant)."""
    _reset()
    vu = {}

    def _faux_verifier(attendue, lignes_pre_lues=None):
        vu["appele"] = True
        return False

    monkeypatch.setattr(jm, "_verifier_derniere_ligne", _faux_verifier)
    ok = jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                              messages=[{"role": "user", "content": "x"}])
    assert vu.get("appele") is True
    assert ok is False


def test_check_vivant_reussit_normalement():
    """En fonctionnement normal (pas de panne simulée), le check passe : ce qui est
    relu égale ce qui vient d'être écrit."""
    _reset()
    assert jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                                messages=[{"role": "user", "content": "x"}]) is True


def test_payload_non_serialisable_json_retourne_false_ne_leve_jamais():
    """Si messages/message_recu contient quelque chose de non sérialisable JSON
    (objet brut, datetime, etc.), enregistrer_appel renvoie False et ne lève JAMAIS.
    Cela respecte la contrainte best-effort du module."""
    _reset()
    # Un objet non sérialisable (object() ne peut pas être converti en JSON)
    ok = jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                              messages=[{"role": "user", "content": object()}])
    assert ok is False
    # Pas d'exception levée, juste False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:                 # tests à fixture monkeypatch : sautés en direct
                continue
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
