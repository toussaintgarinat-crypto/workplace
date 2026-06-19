"""Gateway MCP — expose les outils du Cœur en serveur MCP standard (JSON-RPC 2.0).

Point d'entrée UNIQUE pour des clients/agents tiers (Claude Desktop, IDE, un autre LLM) qui
veulent piloter Workplace. Il NE redéfinit AUCUN outil : il réutilise EXACTEMENT le registre
de l'assistant —
  • `outils.outils_pour(registre)` : outils en dur + capacités DÉCOUVERTES par manifest (S63/S64) ;
  • `outils.executer(nom, args, registre)` : le répartiteur universel vers les briques ;
  • `outils.est_action(nom, registre)` : marque les effets de bord (annotation MCP).

Donc la « découverte dynamique des outils » est gratuite (ajouter `capacites` à un manifest
suffit), et le contexte de l'assistant n'est PAS pollué : c'est un endpoint séparé, parlé par
des clients externes, qui partage seulement le registre.

Transport : Streamable HTTP — un POST JSON-RPC sur `/mcp`. Méthodes : `initialize`,
`tools/list`, `tools/call`, `ping`. Le co-agent planificateur exécutif est exposé comme un
outil ordinaire (`coagent_lancer`) : un client MCP peut donc déléguer une tâche multi-briques
autonome. Sécurité : clé `MCP_KEY` (header) si définie, kill-switch `MCP_ACTIF`. La
confirmation des actions (`confirme=true`) reste EXIGÉE par `outils.executer` — on ne
contourne aucun garde-fou : un agent autonome doit la passer explicitement.
"""
import os

import outils

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "workplace-coeur", "version": "0.1.0"}


def actif() -> bool:
    """Le serveur MCP est-il allumé ? (kill-switch `MCP_ACTIF`, défaut on)."""
    return os.getenv("MCP_ACTIF", "1").lower() not in ("0", "false", "no")


def cle_ok(presentee: str | None) -> bool:
    """Auth optionnelle : si `MCP_KEY` est définie, on l'exige (header) ; sinon mode ouvert."""
    attendue = os.getenv("MCP_KEY")
    return True if not attendue else presentee == attendue


def _outil_mcp(spec: dict, est_action) -> dict:
    """Spec function-calling OpenAI → descripteur d'outil MCP (`name/description/inputSchema`)."""
    f = spec["function"]
    nom = f["name"]
    action = est_action(nom)
    return {
        "name": nom,
        "description": f.get("description", ""),
        "inputSchema": f.get("parameters") or {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": not action, "destructiveHint": bool(action)},
    }


def lister_outils(registre) -> list:
    """Tous les outils du Cœur au format MCP (statiques + dynamiques découverts)."""
    return [_outil_mcp(s, lambda n: outils.est_action(n, registre))
            for s in outils.outils_pour(registre)]


def _rep(id_, result=None, error=None) -> dict:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


async def traiter(corps: dict, registre) -> dict | None:
    """Traite UN message JSON-RPC. Renvoie la réponse, ou None pour une notification."""
    if not isinstance(corps, dict):
        return _rep(None, error={"code": -32600, "message": "Requête JSON-RPC invalide."})
    id_ = corps.get("id")
    methode = corps.get("method")
    params = corps.get("params") or {}

    if methode == "initialize":
        return _rep(id_, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if methode in ("notifications/initialized", "initialized"):
        return None                                   # notification : pas de réponse
    if methode == "ping":
        return _rep(id_, {})
    if methode == "tools/list":
        return _rep(id_, {"tools": lister_outils(registre)})
    if methode == "tools/call":
        nom = params.get("name")
        if not nom:
            return _rep(id_, error={"code": -32602, "message": "Paramètre 'name' manquant."})
        if nom not in {t["name"] for t in lister_outils(registre)}:
            return _rep(id_, error={"code": -32602, "message": f"Outil inconnu : {nom}"})
        try:
            texte = await outils.executer(nom, params.get("arguments") or {}, registre)
            return _rep(id_, {"content": [{"type": "text", "text": texte}], "isError": False})
        except Exception as e:  # noqa: BLE001 — erreur d'EXÉCUTION → isError (convention MCP)
            return _rep(id_, {"content": [{"type": "text", "text": f"Erreur outil : {e}"}],
                              "isError": True})
    if id_ is None:
        return None                                   # notification inconnue : on ignore
    return _rep(id_, error={"code": -32601, "message": f"Méthode inconnue : {methode}"})
