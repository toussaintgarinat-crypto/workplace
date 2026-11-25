import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402
import approbations_canal as canal  # noqa: E402


def _d(**kw):
    base = {"id": "a" * 32, "capacite": "app_reset", "resume": "app_reset(app='crm')",
            "sensibilite": "destructif", "statut": "en_attente", "code": "424242",
            "prerequis": {}, "expire_a": 1.0, "decide_par": None}
    base.update(kw)
    return base


def test_la_charge_ne_contient_jamais_le_code():
    charge = canal.charge_notification(_d())
    assert "code" not in charge and "424242" not in str(charge)


def test_prerequis_non_reunis_pas_de_bouton():
    assert canal.charge_notification(_d(prerequis={"sauvegarde": False}))["prerequis_ok"] is False
    assert canal.charge_notification(_d(prerequis={"sauvegarde": True}))["prerequis_ok"] is True
    assert canal.charge_notification(_d(prerequis={}))["prerequis_ok"] is True


def test_texte_final_par_statut():
    assert "✅" in canal.texte_final(_d(statut="approuvee"))
    assert "❌" in canal.texte_final(_d(statut="refusee"))
    assert "⌛" in canal.texte_final(_d(statut="expiree"))
    assert "424242" not in canal.texte_final(_d(statut="approuvee"))


def test_notifier_ne_leve_jamais_et_stocke_les_messages(monkeypatch, tmp_path):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    a = approbations.creer("c", {}, "r", "reversible")
    # injecter un faux transport : voir approbations_canal._poster (à rendre monkeypatchable)
    async def faux_poster(registre, chemin, corps):
        return {"messages": [{"chat_id": "42", "message_id": 9}]}
    monkeypatch.setattr(canal, "_poster", faux_poster)
    asyncio.run(canal.notifier(object(), a))
    assert approbations.lire(a["id"])["messages"] == [{"chat_id": "42", "message_id": 9}]


def test_brique_injoignable_ne_leve_pas(monkeypatch):
    async def casse(registre, chemin, corps):
        raise RuntimeError("down")
    monkeypatch.setattr(canal, "_poster", casse)
    asyncio.run(canal.notifier(object(), _d()))          # ne doit pas lever
    asyncio.run(canal.mettre_a_jour(object(), _d()))
