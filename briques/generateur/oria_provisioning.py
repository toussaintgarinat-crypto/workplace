"""Provisioning Oria — crée l'espace de messagerie d'une entreprise à la génération.

Modèle (cf. cartographie S3.1) :
  • Auth = compte de service Keycloak `workplace-provisioner` (client confidentiel,
    service account + mapper d'audience → `oria-app`). Le token est accepté par Oria
    et auto-provisionne un utilisateur de service (propriétaire de l'espace).
  • Un « espace entreprise » = un *world* Oria. Un *building* le contient.
  • Un « salon » = une *room* (mappée sur une room Matrix). On crée 1 salon par
    bounded_context de l'audit.

Choix v1 : salons NON chiffrés (type Oria hors « texte/mixte ») pour permettre le
widget de messagerie léger embarqué dans l'app livrée (lecture/écriture directe via
l'API Matrix avec les identifiants de l'utilisateur). L'E2EE complet via l'embed du
frontend Oria reste l'évolution prévue (cf. WORKPLACE.md).

Tout est best-effort : si Oria/Keycloak est injoignable, on lève une exception claire
que l'appelant peut capturer pour générer l'app sans messagerie.
"""
import os

import httpx

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL_INTERNE", "http://host.docker.internal:8081")
ORIA_URL_INTERNE = os.getenv("ORIA_URL_INTERNE", "http://host.docker.internal:8000")
PROVISIONER_CLIENT_ID = os.getenv("ORIA_PROVISIONER_CLIENT", "workplace-provisioner")
PROVISIONER_SECRET = os.getenv("ORIA_PROVISIONER_SECRET", "workplace-provisioner-secret-2026")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "oria")

# Type de room qui n'active PAS le chiffrement côté Oria (encrypt = type in {texte,mixte}).
TYPE_SALON = "canal"


def _token() -> str:
    url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    with httpx.Client(timeout=10) as c:
        r = c.post(url, data={
            "client_id": PROVISIONER_CLIENT_ID,
            "client_secret": PROVISIONER_SECRET,
            "grant_type": "client_credentials",
        })
        r.raise_for_status()
        return r.json()["access_token"]


def _salons_depuis_audit(audit: dict) -> list[str]:
    """1 salon par bounded_context ; repli sur des salons génériques si l'audit est pauvre."""
    noms: list[str] = []
    try:
        bcs = (((audit.get("territoire") or {}).get("ddd") or {}).get("bounded_contexts")) or []
        for bc in bcs:
            if isinstance(bc, dict):
                nom = bc.get("nom") or bc.get("name") or bc.get("titre")
            else:
                nom = str(bc)
            if nom:
                noms.append(str(nom).strip()[:60])
    except Exception:
        pass
    # Dédoublonnage en gardant l'ordre
    vus, uniques = set(), []
    for n in noms:
        k = n.lower()
        if k and k not in vus:
            vus.add(k)
            uniques.append(n)
    if not uniques:
        uniques = ["Général", "Direction", "Opérations"]
    # Toujours un salon d'accueil en tête
    if uniques and uniques[0].lower() not in ("général", "general", "accueil"):
        uniques = ["Général"] + uniques
    return uniques[:10]


def provisionner_espace(nom_entreprise: str, audit: dict, emoji: str = "🏢",
                        couleur: str = "#4F46E5") -> dict:
    """Crée le world + building + salons d'une entreprise. Retourne la carte de l'espace.

    Retour : {world_id, building_id, salons: [{nom, room_id, matrix_room_id}],
              proprietaire_mxid}.
    Lève une exception si Oria/Keycloak est injoignable (l'appelant décide).
    """
    token = _token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    with httpx.Client(timeout=30, headers=headers) as c:
        # Identité du compte de service (propriétaire + créateur des rooms Matrix)
        me = c.get(f"{ORIA_URL_INTERNE}/api/auth/me")
        me.raise_for_status()
        proprietaire_mxid = me.json().get("matrix_user_id")

        # 1. World (espace entreprise)
        w = c.post(f"{ORIA_URL_INTERNE}/api/worlds/", json={
            "nom": nom_entreprise,
            "description": f"Espace de messagerie interne — {nom_entreprise}",
            "emoji": emoji, "couleur": couleur,
        })
        w.raise_for_status()
        world_id = w.json()["id"]

        # 2. Building conteneur (crée des salons par défaut qu'on remplace)
        b = c.post(f"{ORIA_URL_INTERNE}/api/buildings/", json={
            "world_id": world_id, "nom": "Espace de travail",
            "type": "maison", "emoji": "🗂️",
        })
        b.raise_for_status()
        bjson = b.json()
        building_id = bjson["id"]
        for r in bjson.get("rooms", []):
            try:
                c.delete(f"{ORIA_URL_INTERNE}/api/buildings/rooms/{r['id']}")
            except Exception:
                pass

        # 3. Un salon par bounded_context (non chiffré → widget léger)
        salons = []
        for nom in _salons_depuis_audit(audit):
            try:
                rr = c.post(f"{ORIA_URL_INTERNE}/api/buildings/rooms", json={
                    "building_id": building_id, "nom": nom,
                    "type": TYPE_SALON, "emoji": "💬",
                })
                rr.raise_for_status()
                d = rr.json()
                salons.append({
                    "nom": nom,
                    "room_id": d["id"],
                    "matrix_room_id": d.get("matrix_room_id"),
                })
            except Exception as e:
                print(f"[oria_provisioning] salon '{nom}' échoué : {e}")

    return {
        "world_id": world_id,
        "building_id": building_id,
        "salons": salons,
        "proprietaire_mxid": proprietaire_mxid,
    }
