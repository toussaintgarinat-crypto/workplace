"""Gateway MCP — serveur MCP standard par-dessus les outils du Cœur (Sprint S74).

Vérifie le protocole JSON-RPC (initialize/ping/tools/list/tools/call), que la liste d'outils
MCP reprend EXACTEMENT le registre de l'assistant (statiques + capacités découvertes par
manifest), que les actions sont marquées (annotations), que tools/call route vers le
répartiteur universel, et que les garde-fous (méthode/outil inconnus, auth, kill-switch)
répondent honnêtement.

Autonome (asyncio.run, faux registre) — motif du reste de core/.
    $ cd core && python3 test_mcp.py
"""
import asyncio
import json
import os

import mcp
import outils


class _Registre:
    def __init__(self, briques):
        self.briques = briques


def _registre():
    # calcul expose 2 capacités neuves (1 lecture, 1 action) découvertes par manifest.
    return _Registre({
        "calcul": {"nom": "calcul", "port": 5990, "capacites": [
            {"nom": "calcul_lister_noeuds", "description": "liste", "methode": "GET",
             "chemin": "/noeuds", "params": {}, "action": False},
            {"nom": "calcul_etat_muscle", "description": "élit", "methode": "GET",
             "chemin": "/muscle", "params": {"reveiller": {"type": "boolean"}}, "action": True},
        ]},
    })


def _t(corps):
    return asyncio.run(mcp.traiter(corps, _registre()))


# ── Protocole ─────────────────────────────────────────────────────────────────

def test_initialize_annonce_protocole_et_serveur():
    rep = _t({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert rep["jsonrpc"] == "2.0" and rep["id"] == 1
    assert rep["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert rep["result"]["serverInfo"]["name"] == "workplace-coeur"
    assert "tools" in rep["result"]["capabilities"]


def test_notification_initialized_sans_reponse():
    assert _t({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping():
    assert _t({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}


def test_methode_inconnue_erreur():
    rep = _t({"jsonrpc": "2.0", "id": 9, "method": "n_existe_pas"})
    assert rep["error"]["code"] == -32601


# ── tools/list ──────────────────────────────────────────────────────────────

def test_tools_list_reprend_statiques_et_dynamiques():
    rep = _t({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    noms = {t["name"] for t in rep["result"]["tools"]}
    statiques = {o["function"]["name"] for o in outils.OUTILS}
    assert statiques <= noms                                   # rien perdu
    assert {"calcul_lister_noeuds", "calcul_etat_muscle"} <= noms   # nerfs découverts
    # chaque outil a un inputSchema (schéma JSON)
    for t in rep["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object"


def test_tools_list_marque_les_actions():
    rep = _t({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    par_nom = {t["name"]: t for t in rep["result"]["tools"]}
    # lecture : readOnly ; action : destructive (le co-agent/agent MCP le sait)
    assert par_nom["etat_briques"]["annotations"]["readOnlyHint"] is True
    assert par_nom["calcul_etat_muscle"]["annotations"]["destructiveHint"] is True
    assert par_nom["calcul_etat_muscle"]["annotations"]["readOnlyHint"] is False


def test_coagent_expose_comme_outil():
    """Le planificateur exécutif est appelable par un client MCP (outil ordinaire)."""
    rep = _t({"jsonrpc": "2.0", "id": 5, "method": "tools/list"})
    assert "coagent_lancer" in {t["name"] for t in rep["result"]["tools"]}


# ── tools/call ──────────────────────────────────────────────────────────────

def test_tools_call_route_vers_le_repartiteur():
    capte = {}

    async def faux_executer(nom, args, registre):
        capte["nom"], capte["args"] = nom, args
        return json.dumps({"ok": True, "echo": args})

    orig = outils.executer
    outils.executer = faux_executer
    try:
        rep = _t({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                  "params": {"name": "etat_briques", "arguments": {"x": 1}}})
    finally:
        outils.executer = orig
    assert capte["nom"] == "etat_briques" and capte["args"] == {"x": 1}
    res = rep["result"]
    assert res["isError"] is False
    assert res["content"][0]["type"] == "text"
    assert json.loads(res["content"][0]["text"])["ok"] is True


def test_tools_call_outil_inconnu_erreur():
    rep = _t({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
              "params": {"name": "n_existe_pas", "arguments": {}}})
    assert rep["error"]["code"] == -32602


def test_tools_call_erreur_outil_remontee_en_iserror():
    async def boom(nom, args, registre):
        raise RuntimeError("brique en panne")

    orig = outils.executer
    outils.executer = boom
    try:
        rep = _t({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                  "params": {"name": "etat_briques", "arguments": {}}})
    finally:
        outils.executer = orig
    assert rep["result"]["isError"] is True
    assert "panne" in rep["result"]["content"][0]["text"]


# ── Sécurité / interrupteurs ──────────────────────────────────────────────────

def test_cle_ok_exigee_si_definie():
    assert mcp.cle_ok(None) is True                            # pas de MCP_KEY → ouvert
    os.environ["MCP_KEY"] = "s3cr3t"
    try:
        assert mcp.cle_ok("s3cr3t") is True
        assert mcp.cle_ok("faux") is False
    finally:
        os.environ.pop("MCP_KEY", None)


def test_kill_switch():
    assert mcp.actif() is True
    os.environ["MCP_ACTIF"] = "0"
    try:
        assert mcp.actif() is False
    finally:
        os.environ.pop("MCP_ACTIF", None)


def test_tools_call_action_confirmee_bypasse_le_registre_accord():
    """MCP ne passe JAMAIS par accord_action.REGISTRE (S222) : `tools/call` appelle
    `outils.executer` directement. C'est un choix assumé (ADR
    docs/decisions/2026-08-09-gate-action-structurel.md), pas un oubli — ce test fige ce
    comportement pour qu'un futur changement soit délibéré, pas accidentel."""
    import accord_action
    fil_preuve = "fil-preuve-mcp-ignore-registre"
    assert accord_action.REGISTRE.etat(fil_preuve) == {"en_attente": [], "accordees": []}
    capte = {}

    async def faux_executer(nom, args, registre):
        capte["nom"], capte["args"] = nom, args
        return json.dumps({"ok": True})

    orig = outils.executer
    outils.executer = faux_executer
    try:
        rep = _t({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                  "params": {"name": "calcul_etat_muscle",
                             "arguments": {"reveiller": True, "confirme": True}}})
    finally:
        outils.executer = orig
    # Exécuté immédiatement malgré `action: True` et SANS accord préalable dans le
    # registre : c'est le chemin documenté comme non couvert par le gate.
    assert capte["nom"] == "calcul_etat_muscle"
    assert capte["args"] == {"reveiller": True, "confirme": True}
    assert rep["result"]["isError"] is False
    # Toujours vide : cet appel MCP n'a jamais touché le registre d'accords, sous AUCUNE clé.
    assert accord_action.REGISTRE.etat(fil_preuve) == {"en_attente": [], "accordees": []}


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
