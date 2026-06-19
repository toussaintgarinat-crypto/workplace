"""Outils d'auto-amélioration pilotables EN CONVERSATION (S75).

Le cycle S68→S70 (mesure → propose → gate humain) devient pilotable en parlant
(Telegram/chat). On vérifie que : les 5 outils sont déclarés ; les 4 actions sont
gardées par confirmation (et la lecture ne l'est pas) ; le gate refuse tant que
confirme≠true ; et que les décisions appliquées touchent bien le store (sans
jamais auto-câbler une capacité — elle reste une SPÉC à implémenter).

Async via asyncio.run (motif du reste de la suite core/, pas de marqueur pytest).
Les stores sont redirigés vers des fichiers temporaires → aucun /data requis.
"""

import asyncio
import json
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test")  # requis par config_assistant (offline)
_TMP = tempfile.mkdtemp()
os.environ["AMELIORATION_PATH"] = os.path.join(_TMP, "ameliorations.json")
os.environ["CAPACITES_PROPOSEES_PATH"] = os.path.join(_TMP, "capacites.json")

import amelioration  # noqa: E402
import curateur  # noqa: E402
import outils  # noqa: E402

NOMS = {o["function"]["name"] for o in outils.OUTILS}
_NOUVEAUX = {"amelioration_etat", "curateur_lancer", "amelioration_evaluer",
             "amelioration_decider", "capacite_decider"}


# ── Déclaration & gate ───────────────────────────────────────────────────────
def test_outils_amelioration_declares():
    assert _NOUVEAUX <= NOMS


def test_actions_gardees_lecture_libre():
    gardees = {"curateur_lancer", "amelioration_evaluer",
               "amelioration_decider", "capacite_decider"}
    assert gardees <= outils.OUTILS_ACTION
    # la vue d'ensemble est une LECTURE : pas de confirmation.
    assert "amelioration_etat" not in outils.OUTILS_ACTION


def test_curateur_lancer_refuse_sans_confirme():
    out = json.loads(asyncio.run(outils.executer("curateur_lancer", {}, None)))
    assert out.get("confirmation_requise") is True


def test_amelioration_decider_refuse_sans_confirme():
    out = json.loads(asyncio.run(outils.executer(
        "amelioration_decider", {"decision": "appliquer", "id": "x"}, None)))
    assert out.get("confirmation_requise") is True


def test_decision_invalide_message_clair():
    out = asyncio.run(outils.executer(
        "amelioration_decider", {"decision": "n_importe_quoi", "confirme": True}, None))
    assert "valider" in out and "appliquer" in out


# ── Lecture : vue d'ensemble (sans confirmation, sans réseau) ────────────────
def test_amelioration_etat_lecture():
    out = json.loads(asyncio.run(outils.executer("amelioration_etat", {}, None)))
    assert "prompt" in out and "capacites_proposees" in out


# ── Décisions appliquées : le gate touche bien le store ──────────────────────
def _injecter_proposition() -> str:
    """Pose une proposition de prompt « propose » directement dans le store."""
    data = amelioration._charger()
    pid = "test-s75"
    data["propositions"] = [p for p in data.get("propositions", []) if p["id"] != pid]
    data["propositions"].append({"id": pid, "statut": "propose", "addendum": "Sois plus bref."})
    amelioration._sauver(data)
    return pid


def test_decider_appliquer_active_l_addendum():
    pid = _injecter_proposition()
    out = json.loads(asyncio.run(outils.executer(
        "amelioration_decider", {"decision": "appliquer", "id": pid, "confirme": True}, None)))
    assert out["ok"] is True and out["proposition"]["statut"] == "applique"
    # un addendum actif est désormais reflété par lister().
    assert amelioration.lister().get("actif_id") == pid


def test_decider_desactiver_revient_au_fondateur():
    _injecter_proposition()
    asyncio.run(outils.executer(
        "amelioration_decider", {"decision": "appliquer", "id": "test-s75", "confirme": True}, None))
    out = json.loads(asyncio.run(outils.executer(
        "amelioration_decider", {"decision": "desactiver", "confirme": True}, None)))
    assert out.get("ok") is True
    assert amelioration.lister().get("actif_id") in (None, "")


def test_capacite_decider_invalide():
    out = asyncio.run(outils.executer(
        "capacite_decider", {"decision": "auto_cabler", "id": "x", "confirme": True}, None))
    assert "retenir" in out and "rejeter" in out


if __name__ == "__main__":
    for nom, fn in sorted(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {nom}")
    print("test_amelioration_outils : tout vert")
