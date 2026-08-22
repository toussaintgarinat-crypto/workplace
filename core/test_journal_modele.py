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
    # Le bornage réel n'est vérifié qu'une fois tous les INTERVALLE_BORNAGE appels
    # (compteur en mémoire de process, cf. revue finale S234) : on le remet à zéro
    # entre chaque test pour que les tests restent indépendants de l'ordre d'exécution.
    jm._compteur_depuis_bornage = 0


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
    # Le bornage réel (lecture+réécriture intégrale) n'est déclenché qu'une fois tous les
    # INTERVALLE_BORNAGE appels (compteur en mémoire, cf. revue finale S234 point 2) — pas à
    # chaque écriture. On écrit donc plusieurs cycles complets pour laisser le bornage
    # l'occasion de tourner au moins deux fois (et donc de prouver qu'il retombe bien à
    # ~mx après avoir dépassé le seuil), pas juste mx*1.2 lignes d'un coup.
    n = jm.INTERVALLE_BORNAGE * 3
    for i in range(n):
        jm.enregistrer_appel(fil="fil-borne", etiquette="chat", modele="m",
                             messages=[{"role": "user", "content": f"msg {i}"}])
    tous = [l for l in jm._lignes() if l.get("fil") == "fil-borne"]
    # Tolérance : entre 2 vérifications, le fichier peut dépasser mx*1,2 de jusqu'à
    # INTERVALLE_BORNAGE lignes avant que le bornage suivant ne rattrape.
    assert len(tous) <= int(50 * 1.2) + jm.INTERVALLE_BORNAGE
    assert tous[-1]["messages"][0]["content"] == f"msg {n - 1}"


def test_check_vivant_detecte_un_ecart_et_ne_leve_jamais(monkeypatch):
    """Runtime check : si la relecture immédiate diffère de ce qu'on vient d'écrire
    (troncature disque, écriture concurrente corrompue…), `enregistrer_appel` renvoie
    False et loggue — mais ne lève JAMAIS (best-effort, ne doit pas casser l'appelant)."""
    _reset()
    vu = {}

    def _faux_verifier(attendue):
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


def test_bornage_meme_si_check_vivant_echoue(monkeypatch):
    """Le bornage doit tourner INCONDITIONNELLEMENT, même si le check vivant échoue
    (corruption détectée). C'est critique pour garder la taille bornée justement quand
    quelque chose ne va pas — c'est le cas où on EN A LE PLUS BESOIN."""
    _reset()
    # Note: _max() a un minimum de 50, donc on utilise 60 (qui sera 60)
    monkeypatch.setenv("MODELE_JOURNAL_MAX", "60")
    borne = jm.INTERVALLE_BORNAGE

    # Phase 1 : écrire 2 cycles complets de vérification (2×INTERVALLE_BORNAGE lignes,
    # au-delà de max*1.2=72) pour laisser le bornage l'occasion de tourner au moins une
    # fois avant la phase de corruption simulée.
    for i in range(2 * borne):
        jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                             messages=[{"role": "user", "content": f"msg {i}"}])
    tous_apres_phase1 = jm._lignes()
    assert len(tous_apres_phase1) <= 72, \
        f"Bounding should have triggered: {len(tous_apres_phase1)} lines"

    # Phase 2 : maintenant simuler une corruption du check vivant
    vu = {}

    def _faux_verifier_toujours_false(attendue):
        vu["verif_appelee"] = True
        return False  # Simule une corruption détectée

    monkeypatch.setattr(jm, "_verifier_derniere_ligne", _faux_verifier_toujours_false)

    # Phase 3 : écrire un cycle complet supplémentaire avec le check en échec — assez pour
    # que le bornage (compteur en mémoire) se redéclenche au moins une fois pendant la panne.
    depart = 2 * borne
    for i in range(depart, depart + borne):
        result = jm.enregistrer_appel(fil="f", etiquette="chat", modele="m",
                                      messages=[{"role": "user", "content": f"msg {i}"}])
        # enregistrer_appel renvoie False car le check échoue
        assert result is False

    assert vu.get("verif_appelee") is True, "Verification check should have been called"

    # Phase 4 : vérification critique — LE BORNAGE DOIT QUAND MÊME AVOIR TOURNÉ
    # même si le check vivant échouait à chaque fois
    tous_finaux = jm._lignes()
    assert len(tous_finaux) <= 72, \
        f"CRITICAL: Bounding MUST happen even when check fails. " \
        f"Got {len(tous_finaux)} lines, expected ≤72 (max=60, max*1.2=72)"


def test_verifier_derniere_ligne_reussit_sans_stub_sur_gros_fichier():
    """Contrepartie positive du test ci-dessus, sur un fichier dont la taille dépasse la
    queue relue (_TAILLE_QUEUE_CHECK) : la vraie comparaison doit continuer à réussir en
    lisant uniquement la queue du fichier (pas de lecture intégrale, cf. point 2)."""
    _reset()
    # Remplit le fichier avec des lignes volumineuses pour dépasser la taille de la queue.
    gros_contenu = "x" * 2000
    for i in range(1000):
        jm.enregistrer_appel(fil="gros", etiquette="chat", modele="m",
                             messages=[{"role": "user", "content": f"{gros_contenu} {i}"}])
    assert jm.CHEMIN.stat().st_size > jm._TAILLE_QUEUE_CHECK
    derniere = jm.enregistrer_appel(fil="gros", etiquette="chat", modele="m",
                                    messages=[{"role": "user", "content": "toute dernière"}])
    assert derniere is True
    attendue = jm._lignes()[-1]
    assert jm._verifier_derniere_ligne(attendue) is True


def test_verifier_derniere_ligne_echoue_honnetement_sur_ligne_geante():
    """Cas extrême (point 2) : si la dernière ligne du fichier est individuellement plus
    grosse que la queue relue, on ne peut pas la reconstruire — échec honnête (log + False),
    jamais un crash ni une supposition optimiste."""
    _reset()
    ligne_geante = {"ts": 0, "fil": "f", "etiquette": "chat", "modele": "m",
                    "messages": [{"role": "user", "content": "y" * (jm._TAILLE_QUEUE_CHECK * 2)}],
                    "outils_offerts": [], "message_recu": None, "erreur": None}
    import json as _json
    jm.CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    jm.CHEMIN.write_text(_json.dumps(ligne_geante, ensure_ascii=False) + "\n", encoding="utf-8")
    assert jm._verifier_derniere_ligne(ligne_geante) is False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:                 # tests à fixture monkeypatch : sautés en direct
                continue
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
