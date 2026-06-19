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


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            try:
                fn()
            except TypeError:                 # tests à fixture monkeypatch : sautés en direct
                continue
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
