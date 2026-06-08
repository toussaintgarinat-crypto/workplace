"""
Service Matrix — interface entre FastAPI (Oria) et Matrix Synapse.

Toutes les communications avec Synapse passent par ce module.
Utilise l'Application Service token pour agir au nom des utilisateurs Oria.
"""

import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

MATRIX_URL      = os.getenv("MATRIX_HOMESERVER_URL", "http://dendrite:8008")
SERVER_NAME     = os.getenv("MATRIX_SERVER_NAME", "oria.local")
AS_TOKEN        = os.getenv("MATRIX_AS_TOKEN", "")
HS_TOKEN        = os.getenv("MATRIX_HS_TOKEN", "")

TIMEOUT = 10  # secondes


def _headers_as() -> dict:
    """Headers pour les requêtes Application Service (agit globalement)."""
    return {"Authorization": f"Bearer {AS_TOKEN}", "Content-Type": "application/json"}


def _mxid(user_id: str) -> str:
    """Construit le Matrix User ID depuis un ID Oria."""
    return f"@oria_{user_id}:{SERVER_NAME}"


# ─── Provisioning utilisateur ─────────────────────────────────────────────────

def provision_user(user_id: str) -> Optional[dict]:
    """
    Crée un compte Matrix pour un utilisateur Oria.
    Retourne {"user_id": mxid, "access_token": token} ou None si erreur.
    """
    mxid = _mxid(user_id)
    username = f"oria_{user_id}"

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # Créer le compte via l'Application Service
            resp = client.post(
                f"{MATRIX_URL}/_matrix/client/v3/register",
                headers=_headers_as(),
                json={"username": username, "type": "m.login.application_service"},
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(f"Compte Matrix créé : {mxid}")
                # AS registration doesn't return access_token — get one via login
                token = _get_token_for(user_id)
                return {
                    "user_id": data.get("user_id", mxid),
                    "access_token": token.get("access_token", "") if token else "",
                }

            if resp.status_code == 400 and resp.json().get("errcode") == "M_USER_IN_USE":
                logger.info(f"Compte Matrix déjà existant : {mxid}, récupération du token")
                return _get_token_for(user_id)

            logger.warning(f"Erreur provision Matrix {mxid}: {resp.status_code} {resp.text}")
            return None

    except Exception as e:
        logger.error(f"Synapse inaccessible lors du provisioning de {mxid}: {e}")
        return None


def _get_token_for(user_id: str) -> Optional[dict]:
    """Obtient un access_token Matrix pour un user existant via impersonation AS."""
    mxid = _mxid(user_id)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                f"{MATRIX_URL}/_matrix/client/v3/login",
                headers=_headers_as(),
                json={
                    "type": "m.login.application_service",
                    "identifier": {"type": "m.id.user", "user": f"oria_{user_id}"},
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "user_id": data.get("user_id", mxid),
                    "access_token": data.get("access_token", ""),
                }
            logger.warning(f"Échec impersonation {mxid}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Erreur impersonation {mxid}: {e}")
        return None


# ─── Gestion des rooms ────────────────────────────────────────────────────────

def create_room(room_id: str, room_name: str, creator_mxid: str,
                invited_mxids: list, encrypt: bool = False) -> Optional[str]:
    """
    Crée une Matrix Room pour une Room Oria.
    Retourne le matrix_room_id ("!xxx:oria.local") ou None si erreur.
    """
    initial_state = []
    if encrypt:
        initial_state.append({
            "type": "m.room.encryption",
            "content": {"algorithm": "m.megolm.v1.aes-sha2"},
        })

    body = {
        "name": room_name,
        "room_alias_name": f"oria_{room_id}",
        "preset": "private_chat",
        "invite": [m for m in invited_mxids if m != creator_mxid],
        "initial_state": initial_state,
        "creation_content": {"m.federate": False},
    }

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                f"{MATRIX_URL}/_matrix/client/v3/createRoom",
                params={"user_id": creator_mxid},
                headers=_headers_as(),
                json=body,
            )
            if resp.status_code == 200:
                matrix_room_id = resp.json().get("room_id")
                logger.info(f"Room Matrix créée : {matrix_room_id} pour room Oria {room_id}")
                return matrix_room_id
            logger.warning(f"Erreur création room Matrix {room_id}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Synapse inaccessible lors de la création de room {room_id}: {e}")
        return None


def invite_to_room(matrix_room_id: str, mxid: str, inviter_mxid: str) -> bool:
    """Invite un utilisateur Matrix dans une room."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                f"{MATRIX_URL}/_matrix/client/v3/rooms/{matrix_room_id}/invite",
                params={"user_id": inviter_mxid},
                headers=_headers_as(),
                json={"user_id": mxid},
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Erreur invitation {mxid} dans {matrix_room_id}: {e}")
        return False


def create_dm_room(mxid_a: str, mxid_b: str) -> Optional[str]:
    """Crée une room DM privée entre deux utilisateurs Matrix."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                f"{MATRIX_URL}/_matrix/client/v3/createRoom",
                params={"user_id": mxid_a},
                headers=_headers_as(),
                json={
                    "preset": "trusted_private_chat",
                    "is_direct": True,
                    "invite": [mxid_b],
                    "creation_content": {"m.federate": False},
                },
            )
            if resp.status_code == 200:
                return resp.json().get("room_id")
            logger.warning(f"Erreur création DM room {mxid_a}↔{mxid_b}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Synapse inaccessible lors de la création de DM room: {e}")
        return None


# ─── Présence ─────────────────────────────────────────────────────────────────

def set_presence(mxid: str, presence: str, status_msg: str = "") -> None:
    """Met à jour la présence d'un utilisateur Matrix. presence: 'online'|'offline'|'unavailable'"""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            client.put(
                f"{MATRIX_URL}/_matrix/client/v3/presence/{mxid}/status",
                params={"user_id": mxid},
                headers=_headers_as(),
                json={"presence": presence, "status_msg": status_msg},
            )
    except Exception as e:
        logger.error(f"Erreur set_presence {mxid}: {e}")


def send_message(matrix_room_id: str, sender_mxid: str, text: str) -> bool:
    """Envoie un message texte dans une room Matrix."""
    import time
    txn_id = f"oria_{int(time.time() * 1000)}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.put(
                f"{MATRIX_URL}/_matrix/client/v3/rooms/{matrix_room_id}/send/m.room.message/{txn_id}",
                params={"user_id": sender_mxid},
                headers=_headers_as(),
                json={"msgtype": "m.text", "body": text},
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Erreur send_message {matrix_room_id}: {e}")
        return False


# ─── Health check ─────────────────────────────────────────────────────────────

def is_matrix_available() -> bool:
    """Vérifie que le homeserver Matrix (Dendrite) est joignable."""
    try:
        with httpx.Client(timeout=3) as client:
            resp = client.get(f"{MATRIX_URL}/_matrix/client/versions")
            return resp.status_code == 200
    except Exception:
        return False


# Alias pour la compatibilité avec le code existant
is_synapse_available = is_matrix_available
