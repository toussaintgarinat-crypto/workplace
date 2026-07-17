"""Adaptateurs de réseaux — registre PROVIDER-AGNOSTIQUE (un réseau = un adaptateur).

Même esprit que `briques/images/fournisseurs.py` : chaque messagerie expose la MÊME interface
minimale, se configure UNIQUEMENT par variables d'environnement (jamais de secret en dur), et
si elle n'est pas configurée elle est simplement « non disponible » — repli honnête, on ne
simule jamais un réseau.

Interface d'un adaptateur :
    nom                                  identifiant court (clé du registre) ;
    configure() -> bool                  les identifiants sont-ils présents ? (sync, sans réseau) ;
    verifier_webhook(headers, corps)     la requête entrante est-elle authentique ? (signature) ;
    parser_entrant(payload) -> [Entrant] messages reçus extraits du corps du webhook ;
    async recuperer() -> [Entrant]       (optionnel) tirage actif des messages (Telegram getUpdates) ;
    async envoyer(id_externe, texte)     réponse sortante vers l'interlocuteur.

Réseaux livrés : telegram (le plus simple à prouver LIVE), whatsapp (Cloud API officielle),
discord (interactions signées Ed25519), email_sms (squelette honnête, non configuré tant
qu'aucun fournisseur n'est branché).
"""
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Optional

import httpx

try:
    from pywebpush import webpush, WebPushException
except Exception:  # noqa: BLE001 — dépendance optionnelle, repli honnête
    webpush = None
    class WebPushException(Exception):  # type: ignore
        pass

import appareils
import correspondance
import stockage


@dataclass
class Entrant:
    """Un message reçu, normalisé quel que soit le réseau."""
    reseau: str
    id_externe: str            # de QUI / vers où répondre (chat_id, numéro, user/canal)
    texte: str
    nom: Optional[str] = None  # nom affiché de l'interlocuteur (si fourni)
    media_id: Optional[str] = None    # identifiant de fichier média côté réseau (message vocal)
    media_type: Optional[str] = None  # "audio" pour un message vocal (sinon None)
    media_nom: Optional[str] = None   # nom de fichier suggéré (extension utile au moteur STT)


class Adaptateur:
    nom = "base"

    def configure(self) -> bool:
        return False

    def verifier_webhook(self, headers: dict, corps: bytes) -> bool:
        return True

    def parser_entrant(self, payload: dict) -> list:
        return []

    async def recuperer(self) -> list:
        return []

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        raise NotImplementedError

    async def telecharger_media(self, media_id: str) -> bytes:
        """Récupère les octets d'un média (message vocal) à partir de son identifiant réseau.

        Par défaut : non supporté (la plupart des réseaux n'exposent pas encore le vocal ici)."""
        raise NotImplementedError

    async def envoyer_audio(self, id_externe: str, audio: bytes, format: str = "ogg") -> bool:
        """Envoie une réponse VOCALE (octets audio). Par défaut : non supporté."""
        raise NotImplementedError


def _entete(headers: dict, nom: str) -> Optional[str]:
    """Lit un en-tête sans se soucier de la casse."""
    nom = nom.lower()
    for k, v in (headers or {}).items():
        if k.lower() == nom:
            return v
    return None


# ── Telegram ──────────────────────────────────────────────────────────────────
class Telegram(Adaptateur):
    """Bot Telegram. Le plus simple : un token via @BotFather, aucune URL publique requise
    (on tire les messages par `getUpdates`). Sait aussi recevoir un webhook signé."""
    nom = "telegram"

    def _token(self) -> Optional[str]:
        return os.getenv("TELEGRAM_BOT_TOKEN") or None

    def configure(self) -> bool:
        return bool(self._token())

    def _api(self, methode: str) -> str:
        return f"https://api.telegram.org/bot{self._token()}/{methode}"

    def verifier_webhook(self, headers: dict, corps: bytes) -> bool:
        secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
        if not secret:
            return True                          # pas de secret configuré → on n'exige rien
        return _entete(headers, "X-Telegram-Bot-Api-Secret-Token") == secret

    def parser_entrant(self, payload: dict) -> list:
        msg = (payload or {}).get("message") or (payload or {}).get("edited_message") or {}
        chat = msg.get("chat") or {}
        if not chat.get("id"):
            return []
        de = msg.get("from") or {}
        nom = de.get("first_name") or chat.get("title") or chat.get("username")
        texte = (msg.get("text") or "").strip()
        if texte:
            return [Entrant(self.nom, str(chat["id"]), texte, nom)]
        # Pas de texte : message vocal (`voice`, Ogg/Opus) ou fichier audio (`audio`).
        # On le porte vers le pont qui le transcrira (Whisper local) avant de relayer.
        voix = msg.get("voice") or msg.get("audio")
        if voix and voix.get("file_id"):
            ext = "ogg" if msg.get("voice") else (
                (voix.get("file_name") or "audio.mp3").rsplit(".", 1)[-1] or "mp3")
            return [Entrant(self.nom, str(chat["id"]), "", nom,
                            media_id=voix["file_id"], media_type="audio",
                            media_nom=f"voix.{ext}")]
        return []

    async def telecharger_media(self, media_id: str) -> bytes:
        """getFile → chemin → téléchargement des octets depuis l'API fichiers de Telegram."""
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(self._api("getFile"), params={"file_id": media_id})
            r.raise_for_status()
            chemin = (r.json().get("result") or {}).get("file_path")
            if not chemin:
                raise RuntimeError("Telegram getFile : aucun file_path renvoyé.")
            url = f"https://api.telegram.org/file/bot{self._token()}/{chemin}"
            f = await c.get(url)
            f.raise_for_status()
            return f.content

    async def recuperer(self) -> list:
        if not self.configure():
            return []
        offset = stockage.lire_json("telegram_offset.json", {}).get("offset", 0)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(self._api("getUpdates"), params={"offset": offset, "timeout": 0})
            r.raise_for_status()
            data = r.json()
        entrants, dernier = [], offset
        for upd in data.get("result", []):
            dernier = max(dernier, upd.get("update_id", 0) + 1)
            entrants.extend(self.parser_entrant(upd))
        if dernier != offset:
            stockage.ecrire_json("telegram_offset.json", {"offset": dernier})
        return entrants

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self._api("sendMessage"),
                             json={"chat_id": id_externe, "text": texte})
            r.raise_for_status()
        return True

    async def envoyer_audio(self, id_externe: str, audio: bytes, format: str = "ogg") -> bool:
        """Réponse vocale : `sendVoice` pour de l'Ogg/Opus (bulle vocale native), sinon
        `sendAudio` (mp3/wav…). Telegram exige de l'Ogg/Opus pour la bulle vocale."""
        if (format or "").lower() in ("ogg", "oga", "opus"):
            methode, champ, nom = "sendVoice", "voice", "voix.ogg"
        else:
            methode, champ, nom = "sendAudio", "audio", f"voix.{format or 'mp3'}"
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(self._api(methode), data={"chat_id": id_externe},
                             files={champ: (nom, audio, "application/octet-stream")})
            r.raise_for_status()
        return True


# ── WhatsApp (Cloud API officielle, Meta) ──────────────────────────────────────
class WhatsApp(Adaptateur):
    """WhatsApp Cloud API : webhook signé HMAC-SHA256, envoi via la Graph API. Demande un
    compte Meta Business (setup plus lourd que Telegram, d'où la preuve LIVE en second)."""
    nom = "whatsapp"

    def configure(self) -> bool:
        return bool(os.getenv("WHATSAPP_TOKEN") and os.getenv("WHATSAPP_PHONE_ID"))

    def verifier_get(self, params: dict) -> Optional[str]:
        """Vérification d'abonnement Meta : renvoie le `hub.challenge` si le token correspond."""
        attendu = os.getenv("WHATSAPP_VERIFY_TOKEN")
        if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == attendu:
            return params.get("hub.challenge")
        return None

    def verifier_webhook(self, headers: dict, corps: bytes) -> bool:
        secret = os.getenv("WHATSAPP_APP_SECRET")
        if not secret:
            return True                          # pas de secret app → on ne peut pas vérifier
        signature = _entete(headers, "X-Hub-Signature-256") or ""
        attendu = "sha256=" + hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, attendu)

    def parser_entrant(self, payload: dict) -> list:
        entrants = []
        for entry in (payload or {}).get("entry", []):
            for change in entry.get("changes", []):
                valeur = change.get("value") or {}
                noms = {c.get("wa_id"): (c.get("profile") or {}).get("name")
                        for c in valeur.get("contacts", [])}
                for msg in valeur.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    de = msg.get("from")
                    texte = (msg.get("text") or {}).get("body", "").strip()
                    if de and texte:
                        entrants.append(Entrant(self.nom, str(de), texte, noms.get(de)))
        return entrants

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        version = os.getenv("WHATSAPP_API_VERSION", "v21.0")
        phone = os.getenv("WHATSAPP_PHONE_ID")
        url = f"https://graph.facebook.com/{version}/{phone}/messages"
        entetes = {"Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}"}
        corps = {"messaging_product": "whatsapp", "to": id_externe,
                 "type": "text", "text": {"body": texte}}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers=entetes, json=corps)
            r.raise_for_status()
        return True


# ── Discord (interactions signées Ed25519) ─────────────────────────────────────
class Discord(Adaptateur):
    """Discord via endpoint d'interactions signé Ed25519 (PING/PONG + commandes). Note honnête :
    les messages privés hors slash-commands passent par la passerelle Gateway (websocket), non
    couverte ici — extension prévue. L'envoi traite `id_externe` comme un identifiant de canal."""
    nom = "discord"

    def configure(self) -> bool:
        return bool(os.getenv("DISCORD_PUBLIC_KEY"))

    def verifier_webhook(self, headers: dict, corps: bytes) -> bool:
        cle = os.getenv("DISCORD_PUBLIC_KEY")
        signature = _entete(headers, "X-Signature-Ed25519")
        horodatage = _entete(headers, "X-Signature-Timestamp")
        if not (cle and signature and horodatage):
            return False
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(cle))
            pk.verify(bytes.fromhex(signature), horodatage.encode() + corps)
            return True
        except InvalidSignature:
            return False
        except Exception:  # noqa: BLE001 — lib absente / clé malformée → refus honnête
            return False

    def parser_entrant(self, payload: dict) -> list:
        if (payload or {}).get("type") == 1:                     # PING : pas un message
            return []
        data = payload.get("data") or {}
        texte = ""
        for opt in data.get("options", []):                     # slash-command : 1ʳᵉ option texte
            if isinstance(opt.get("value"), str):
                texte = opt["value"].strip()
                break
        texte = texte or (payload.get("content") or "").strip()
        membre = payload.get("member") or {}
        user = membre.get("user") or payload.get("user") or {}
        cible = payload.get("channel_id") or user.get("id")
        if not (texte and cible):
            return []
        return [Entrant(self.nom, str(cible), texte, user.get("username"))]

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        jeton = os.getenv("DISCORD_BOT_TOKEN")
        if not jeton:
            return False
        url = f"https://discord.com/api/v10/channels/{id_externe}/messages"
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(url, headers={"Authorization": f"Bot {jeton}"},
                             json={"content": texte})
            r.raise_for_status()
        return True


# ── Email / SMS (squelette honnête) ────────────────────────────────────────────
class EmailSms(Adaptateur):
    """Canaux additionnels (email entrant / SMS via fournisseur). Squelette honnête : tant
    qu'aucun fournisseur n'est branché (`EMAILSMS_FOURNISSEUR`), l'adaptateur est « non
    configuré » et le pont l'ignore — on ne prétend jamais avoir envoyé un message."""
    nom = "email_sms"

    def configure(self) -> bool:
        return bool(os.getenv("EMAILSMS_FOURNISSEUR"))

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        # Brancher ici un fournisseur (SMTP entrant, Twilio, Vonage…) le moment venu.
        return False


# ── Web Push (S178) ─────────────────────────────────────────────────────────────
class WebPush(Adaptateur):
    """Notifications push web (navigateur / PWA). `id_externe` = endpoint de l'appareil ;
    les clés sont résolues dans le magasin `appareils`. VAPID = identité du serveur push."""
    nom = "webpush"

    def _cle_privee(self):
        return os.getenv("VAPID_PRIVATE_KEY") or None

    def configure(self) -> bool:
        return bool(webpush and self._cle_privee() and os.getenv("VAPID_SUBJECT"))

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        app = appareils.par_endpoint(id_externe)
        if not app or webpush is None:
            return False
        titre, _, corps = texte.partition("\n")
        payload = json.dumps({"titre": titre.strip(), "corps": corps.strip(),
                              "url": "/app", "tag": "workplace"})
        info = {"endpoint": app["endpoint"], "keys": app.get("keys") or {}}
        try:
            webpush(subscription_info=info, data=payload,
                    vapid_private_key=self._cle_privee(),
                    vapid_claims={"sub": os.getenv("VAPID_SUBJECT")})
            return True
        except WebPushException as ex:  # noqa: BLE001
            code = getattr(getattr(ex, "response", None), "status_code", None)
            if code in (404, 410):
                appareils.retirer(id_externe)   # appareil mort → purge
                try:
                    correspondance.delier("webpush", id_externe)   # ne plus le lister comme cible
                except Exception:  # noqa: BLE001 — best-effort, ne doit jamais faire remonter
                    pass
            return False
        except Exception:  # noqa: BLE001 — best-effort
            return False


# ── Registre ───────────────────────────────────────────────────────────────────
REGISTRE: dict[str, Adaptateur] = {
    "telegram": Telegram(),
    "whatsapp": WhatsApp(),
    "discord": Discord(),
    "email_sms": EmailSms(),
    "webpush": WebPush(),
}

_ORDRE_DEFAUT = ["telegram", "whatsapp", "discord", "email_sms", "webpush"]


def ordre() -> list:
    """Ordre de préférence des réseaux (env `CONNEXION_RESEAUX`, sinon défaut)."""
    brut = os.getenv("CONNEXION_RESEAUX", "")
    demande = [x.strip() for x in brut.split(",") if x.strip()]
    valides = [x for x in demande if x in REGISTRE]
    return valides + [x for x in _ORDRE_DEFAUT if x not in valides]


def disponibles() -> list:
    """Réseaux réellement configurés (identifiants présents)."""
    return [n for n in ordre() if REGISTRE[n].configure()]


def obtenir(nom: str) -> Optional[Adaptateur]:
    return REGISTRE.get(nom)
