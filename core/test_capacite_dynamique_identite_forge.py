"""S228 (revue finale, Finding C1b) — l'identité réelle traverse le dispatch DYNAMIQUE
vers l'adaptateur Forge.

Le Cœur atteint les briques de deux façons : les outils CÂBLÉS (`_forge_appel`, qui
envoie depuis toujours `contexte_tenant.entetes_forge()` → `X-Forge-User-Token`) et le
dispatch DYNAMIQUE des capacités déclarées en manifeste (`_appel_dynamique`), qui
n'envoyait QUE `_entetes_brique` (`X-Compte-Id` / `X-API-Key`).

Conséquence avant correction : toute capacité `forge_*` du manifeste s'exécutait sous le
compte de SERVICE de l'adaptateur. Pour l'entretien guidé S228, dont le core scope sur
`Ventures.owner_id == user.sub`, la venture du dirigeant n'était jamais trouvée → 404 à
chaque tour.

Miroir côté brique : `briques/forge/test_propagation_identite.py` (mêmes scénarios, mais
côté adaptateur). Aucun réseau : le client HTTP est faux et capture les en-têtes.
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import contexte_tenant  # noqa: E402
import outils_communs  # noqa: E402


class _FauxReponse:
    status_code = 200

    def json(self):
        return {"ok": True}


class _FauxClient:
    """Capture les en-têtes du dernier appel ; ne touche jamais le réseau."""

    def __init__(self):
        self.dernier_headers = None

    async def request(self, methode, url, headers=None, **kw):
        self.dernier_headers = headers or {}
        return _FauxReponse()


def _cap(brique: str, nom: str) -> dict:
    return {
        "nom": nom, "brique": brique, "methode": "POST",
        "chemin": "/ventures/{id}/entretien/demarrer",
        "url": f"http://{brique}:5700/ventures/{{id}}/entretien/demarrer",
    }


def _appeler(cap: dict, token: str | None) -> dict:
    client = _FauxClient()
    jetons = contexte_tenant.definir_contexte(user_token=token) if token else None
    try:
        asyncio.run(outils_communs._appel_dynamique(client, cap, {"id": "venture-1"}))
    finally:
        if jetons is not None:
            contexte_tenant.reinitialiser(jetons)
    return client.dernier_headers


def test_capacite_forge_propage_le_jeton_utilisateur():
    entetes = _appeler(_cap("forge", "forge_entretien_demarrer"), "USER-JWT-123")
    assert entetes.get("X-Forge-User-Token") == "Bearer USER-JWT-123", entetes


def test_capacite_forge_conserve_les_entetes_de_brique():
    """La propagation d'identité s'AJOUTE aux en-têtes de service — elle ne les remplace
    pas (sinon `X-API-Key` disparaîtrait et la brique refuserait l'appel)."""
    entetes = _appeler(_cap("forge", "forge_entretien_demarrer"), "USER-JWT-123")
    assert entetes.get("X-Compte-Id"), entetes


def test_capacite_forge_sans_jeton_ne_pose_pas_l_entete():
    """Sans jeton utilisateur (mono-user), rien n'est posé : l'adaptateur retombe sur son
    token de service, flux S17/S24 inchangé."""
    entetes = _appeler(_cap("forge", "forge_entretien_demarrer"), None)
    assert "X-Forge-User-Token" not in entetes, entetes


def test_une_autre_brique_ne_recoit_jamais_le_jeton_forge():
    """Cas spécial volontairement borné à `forge` : `X-Forge-User-Token` est propre à
    l'adaptateur Forge, le diffuser à toutes les briques serait une fuite de JWT."""
    cap = _cap("veille-info", "veille_digest")
    cap["url"] = "http://veille-info:6120/digest"
    cap["chemin"] = "/digest"
    entetes = _appeler(cap, "USER-JWT-123")
    assert "X-Forge-User-Token" not in entetes, entetes
