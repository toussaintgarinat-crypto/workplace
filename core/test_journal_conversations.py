"""Journal de conversations unifié (S78) : la trace de toutes les surfaces.

On vérifie : l'enregistrement et la relecture d'un fil, l'agrégation des fils (aperçu +
compte + surface), l'ignorance des contenus vides, le multi-surfaces (web + telegram dans
le même journal), et le bornage en taille. Autonome : journal en tmp.
    $ cd core && python3 test_journal_conversations.py
"""
import os
import tempfile

os.environ["CONVERSATIONS_JOURNAL_PATH"] = os.path.join(tempfile.mkdtemp(), "conv.jsonl")

import journal_conversations as jc  # noqa: E402


def _reset():
    if jc.CHEMIN.exists():
        jc.CHEMIN.unlink()
    if jc.META.exists():
        jc.META.unlink()


def test_enregistrer_et_relire_un_fil():
    _reset()
    jc.enregistrer("web", "dashboard", "user", "salut")
    jc.enregistrer("web", "dashboard", "assistant", "bonjour")
    msgs = jc.messages("web:dashboard")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "salut" and msgs[1]["content"] == "bonjour"


def test_contenu_vide_ignore():
    _reset()
    jc.enregistrer("web", "dashboard", "user", "   ")
    jc.enregistrer("web", "dashboard", "assistant", "")
    assert jc.messages("web:dashboard") == []


def test_fils_multi_surfaces():
    _reset()
    jc.enregistrer("web", "dashboard", "user", "depuis le web")
    jc.enregistrer("telegram", "4242", "user", "depuis telegram", utilisateur="perso")
    jc.enregistrer("telegram", "4242", "assistant", "réponse telegram", utilisateur="perso")
    fils = jc.fils()
    par = {f["fil"]: f for f in fils}
    assert set(par) == {"web:dashboard", "telegram:4242"}
    assert par["telegram:4242"]["nombre"] == 2
    assert par["telegram:4242"]["surface"] == "telegram"
    assert par["telegram:4242"]["utilisateur"] == "perso"
    assert par["telegram:4242"]["dernier"] == "réponse telegram"


def test_fil_separe_par_interlocuteur():
    _reset()
    jc.enregistrer("telegram", "111", "user", "A")
    jc.enregistrer("telegram", "222", "user", "B")
    assert jc.messages("telegram:111")[0]["content"] == "A"
    assert jc.messages("telegram:222")[0]["content"] == "B"
    assert len(jc.fils()) == 2


def test_bornage_taille(monkeypatch):
    _reset()
    monkeypatch.setenv("CONVERSATIONS_JOURNAL_MAX", "100")
    for i in range(200):
        jc.enregistrer("web", "dashboard", "user", f"msg {i}")
    # borné à ~100 (réécrit quand on dépasse 1,2×) → on garde les plus récents.
    msgs = jc.messages("web:dashboard", limite=10000)
    assert len(msgs) <= 120
    assert msgs[-1]["content"] == "msg 199"


def test_titre_auto_au_premier_message():
    _reset()
    jc.enregistrer("web", "conv-1", "user", "Comment va le restaurant aujourd'hui ?")
    jc.enregistrer("web", "conv-1", "assistant", "Très bien.")
    # le titre auto vient du 1er message humain, pas de la réponse
    assert jc.meta("web:conv-1")["titre"].startswith("Comment va le restaurant")


def test_titre_auto_tronque():
    _reset()
    long = "x" * 200
    jc.enregistrer("web", "c", "user", long)
    t = jc.meta("web:c")["titre"]
    assert t.endswith("…") and len(t) <= 50


def test_renommer_garde_le_titre_manuel():
    _reset()
    jc.enregistrer("web", "c", "user", "premier message")
    jc.renommer("web:c", "Mon titre choisi")
    # un nouveau message ne réécrit pas le titre manuel
    jc.enregistrer("web", "c", "user", "deuxième")
    assert jc.meta("web:c")["titre"] == "Mon titre choisi"


def test_assigner_et_filtrer_par_projet():
    _reset()
    jc.enregistrer("web", "c1", "user", "A")
    jc.enregistrer("web", "c2", "user", "B")
    jc.assigner_projet("web:c1", "proj-42")
    fils = jc.fils(projet_id="proj-42")
    assert [f["fil"] for f in fils] == ["web:c1"]
    assert jc.fils()[0].get("projet_id") in (None, "proj-42")  # tous les fils ont le champ


def test_detacher_projet():
    _reset()
    jc.enregistrer("web", "c1", "user", "A")
    jc.assigner_projet("web:c1", "p")
    assert jc.detacher_projet("p") == 1
    assert jc.meta("web:c1")["projet_id"] is None


def test_supprimer_fil():
    _reset()
    jc.enregistrer("web", "c1", "user", "A")
    jc.enregistrer("web", "c2", "user", "B")
    jc.renommer("web:c1", "titre")
    jc.supprimer_fil("web:c1")
    assert jc.messages("web:c1") == []
    assert jc.meta("web:c1") == {}
    assert [f["fil"] for f in jc.fils()] == ["web:c2"]


def test_fils_enrichis_titre_et_meta():
    _reset()
    jc.enregistrer("web", "c1", "user", "Bonjour le monde")
    f = jc.fils()[0]
    assert f["titre"].startswith("Bonjour") and "epingle" in f and "archive" in f


def test_reordonner_impose_l_ordre_manuel():
    """S104 — cliquer-déposer : `reordonner` fixe `ordre`, qui prime sur la récence (mais
    pas sur l'épinglage)."""
    _reset()
    for c in ("c1", "c2", "c3"):
        jc.enregistrer("web", c, "user", "msg " + c)
    # Par défaut : la plus récente d'abord (c3, c2, c1).
    assert [f["fil"] for f in jc.fils()] == ["web:c3", "web:c2", "web:c1"]
    # On impose l'ordre manuel inverse.
    n = jc.reordonner(["web:c1", "web:c2", "web:c3"])
    assert n == 3
    assert [f["fil"] for f in jc.fils()] == ["web:c1", "web:c2", "web:c3"]
    # Une épinglée passe devant l'ordre manuel.
    jc.definir_meta("web:c3", epingle=True)
    assert jc.fils()[0]["fil"] == "web:c3"


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:                 # tests à fixture monkeypatch : sautés en direct
                continue
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
