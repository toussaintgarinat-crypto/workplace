"""Fournisseurs de boîte mail — interface PROVIDER-AGNOSTIQUE, **lecture seule** (v0.1.0).

Deux fournisseurs, choisis selon qu'un compte IMAP est configuré pour le tenant :

  • `Mock` : par défaut, **honnête**. Aucune connexion réseau, une petite boîte SIMULÉE
             seedée (factures, rdv, perso, newsletter…) pour la démo et les tests. Tous les
             messages portent `source="simule"` : jamais un faux mail présenté comme réel.
  • `Imap` : réel via `imaplib` (stdlib) en **TLS**, ouvert en **READ-ONLY** (`select(..., readonly=True)`)
             — on ne touche JAMAIS au serveur (pas de \\Seen posé, pas de suppression/déplacement).
             Mot de passe d'application (Gmail/Outlook/n'importe quel IMAP). Import paresseux : le
             mock et les tests tournent sans rien installer.

Le mot de passe ne transite jamais en clair dans une réponse, un log ou une erreur.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header

# ── Fournisseur MOCK (honnête, boîte simulée seedée) ─────────────────────────
_SEED = [
    {"id": "m1", "de": "compta@hebergeur-cloud.fr", "de_nom": "Hébergeur Cloud",
     "sujet": "Votre facture de juin est disponible",
     "extrait": "Bonjour, votre facture FAC-2026-06 d'un montant de 49,00 € est prête.",
     "corps": "Bonjour,\n\nVotre facture FAC-2026-06 d'un montant de 49,00 € est disponible "
              "dans votre espace client. Le prélèvement interviendra le 5 juillet.\n\nCordialement,\nLe service compta",
     "lu": False, "dossier": "INBOX"},
    {"id": "m2", "de": "marina@example.com", "de_nom": "Marina",
     "sujet": "On se cale pour le déjeuner de jeudi ?",
     "extrait": "Coucou ! Tu es dispo jeudi midi pour un déjeuner rapide vers 12h30 ?",
     "corps": "Coucou !\n\nTu es dispo jeudi midi pour un déjeuner rapide vers 12h30 ? "
              "On pourrait essayer le nouveau resto à côté du bureau.\n\nBisous,\nMarina",
     "lu": False, "dossier": "INBOX"},
    {"id": "m3", "de": "no-reply@reseau-social.com", "de_nom": "RéseauSocial",
     "sujet": "Nouvelle connexion à votre compte",
     "extrait": "Une connexion a été détectée depuis un nouvel appareil. Si ce n'est pas vous…",
     "corps": "Une connexion a été détectée depuis un nouvel appareil (Paris, FR). "
              "Si ce n'est pas vous, sécurisez votre compte.",
     "lu": False, "dossier": "INBOX"},
    {"id": "m4", "de": "newsletter@boutique-deco.fr", "de_nom": "Boutique Déco",
     "sujet": "🔥 Soldes : -50% sur tout le mobilier ce week-end !",
     "extrait": "Profitez de -50% sur une sélection de meubles. Offre valable jusqu'à dimanche.",
     "corps": "Soldes exceptionnels ! -50% sur le mobilier. Cliquez pour en profiter. "
              "Pour vous désabonner, cliquez ici.",
     "lu": True, "dossier": "INBOX"},
    {"id": "m5", "de": "thomas.client@entreprise.com", "de_nom": "Thomas (client)",
     "sujet": "URGENT — relance sur le devis signé",
     "extrait": "Bonjour, je n'ai toujours pas reçu le démarrage des travaux promis lundi…",
     "corps": "Bonjour,\n\nJe me permets de vous relancer : nous avions convenu d'un démarrage "
              "lundi et je n'ai aucune nouvelle. C'est urgent pour nous.\n\nMerci de me rappeler.\nThomas",
     "lu": False, "dossier": "INBOX"},
    {"id": "m6", "de": "rdv@cabinet-medical.fr", "de_nom": "Cabinet médical",
     "sujet": "Confirmation de votre rendez-vous du 28 juin",
     "extrait": "Nous vous confirmons votre rendez-vous le 28 juin à 9h15.",
     "corps": "Bonjour, nous vous confirmons votre rendez-vous le 28 juin à 9h15. "
              "Merci d'arriver 5 minutes en avance.",
     "lu": True, "dossier": "INBOX"},
    {"id": "m7", "de": "support@outil-saas.io", "de_nom": "Outil SaaS",
     "sujet": "Votre abonnement sera renouvelé dans 3 jours",
     "extrait": "Votre abonnement Pro (19 €/mois) sera renouvelé automatiquement le 24 juin.",
     "corps": "Votre abonnement Pro (19 €/mois) sera renouvelé automatiquement le 24 juin. "
              "Gérez votre abonnement depuis votre espace.",
     "lu": False, "dossier": "INBOX"},
    {"id": "m8", "de": "papa@example.com", "de_nom": "Papa",
     "sujet": "Photos du week-end",
     "extrait": "Je t'envoie les quelques photos du week-end dernier, on s'est bien amusés !",
     "corps": "Coucou,\n\nJe t'envoie les quelques photos du week-end dernier, on s'est bien "
              "amusés ! Appelle-nous quand tu peux.\n\nPapa",
     "lu": True, "dossier": "INBOX"},
]


class Mock:
    """Boîte SIMULÉE locale. Aucune connexion : sert la démo, les tests et le dev souverain."""

    nom = "mock"

    def recuperer(self, dossier: str = "INBOX", limite: int = 50) -> list[dict]:
        msgs = [dict(m, source="simule") for m in _SEED if m["dossier"] == dossier]
        return msgs[:limite]


# ── Fournisseur IMAP réel (lecture seule) ────────────────────────────────────
def _decoder(brut) -> str:
    """Décode un en-tête MIME (sujet/expéditeur encodés) en texte lisible."""
    if not brut:
        return ""
    try:
        return str(make_header(decode_header(brut)))
    except Exception:  # noqa: BLE001 — un en-tête tordu ne doit pas casser la liste
        return str(brut)


def _extrait_corps(msg: email.message.Message, limite: int = 600) -> tuple[str, str]:
    """(corps_texte, extrait) — privilégie le text/plain, ignore les pièces jointes."""
    corps = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition") or ""):
                try:
                    corps = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace")
                    break
                except Exception:  # noqa: BLE001
                    continue
    else:
        try:
            corps = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            corps = ""
    corps = re.sub(r"\n{3,}", "\n\n", corps).strip()
    extrait = re.sub(r"\s+", " ", corps)[:limite].strip()
    return corps, extrait


class Imap:
    """Connexion IMAP réelle, **lecture seule**. `compte` = {host, port, utilisateur, mot_de_passe}.

    On ouvre la boîte en `readonly=True` : lire un message ne le marque PAS comme lu côté serveur
    et rien n'est jamais supprimé/déplacé. Le drapeau « lu » renvoyé reflète l'état serveur (\\Seen)."""

    nom = "imap"

    def __init__(self, compte: dict):
        self.host = compte["host"]
        self.port = int(compte.get("port") or 993)
        self.utilisateur = compte["utilisateur"]
        self._mdp = compte["mot_de_passe"]

    def _connecter(self) -> imaplib.IMAP4_SSL:
        m = imaplib.IMAP4_SSL(self.host, self.port)
        m.login(self.utilisateur, self._mdp)
        return m

    def recuperer(self, dossier: str = "INBOX", limite: int = 50) -> list[dict]:
        m = self._connecter()
        try:
            m.select(dossier, readonly=True)  # READ-ONLY : on ne modifie jamais la boîte
            typ, data = m.search(None, "ALL")
            if typ != "OK":
                return []
            ids = data[0].split()[-limite:]  # les plus récents
            out: list[dict] = []
            for num in reversed(ids):
                typ, fetched = m.fetch(num, "(BODY.PEEK[] FLAGS)")  # PEEK = ne pose pas \Seen
                if typ != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                flags = b""
                if len(fetched) > 1 and isinstance(fetched[-1], bytes):
                    flags = fetched[-1]
                elif isinstance(fetched[0][0], bytes):
                    flags = fetched[0][0]
                msg = email.message_from_bytes(fetched[0][1])
                nom, adresse = email.utils.parseaddr(_decoder(msg.get("From")))
                corps, extrait = _extrait_corps(msg)
                out.append({
                    "id": num.decode(),
                    "de": adresse,
                    "de_nom": nom or adresse,
                    "sujet": _decoder(msg.get("Subject")),
                    "date": _date_iso(msg.get("Date")),
                    "extrait": extrait,
                    "corps": corps,
                    "lu": b"\\Seen" in flags,
                    "dossier": dossier,
                    "source": "imap",
                })
            return out
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass


def _date_iso(brut) -> str:
    """En-tête Date → ISO 8601 (UTC). Vide si illisible."""
    try:
        dt = email.utils.parsedate_to_datetime(brut)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return ""


# ── Sélection du fournisseur ─────────────────────────────────────────────────
def fournisseur_pour(compte: dict | None):
    """Compte IMAP complet → `Imap` (réel) ; sinon → `Mock` (boîte simulée honnête)."""
    if compte and compte.get("host") and compte.get("utilisateur") and compte.get("mot_de_passe"):
        return Imap(compte)
    return Mock()


def etat_config(compte: dict | None) -> dict:
    """État HONNÊTE de la boîte (jamais d'identifiant en clair). Sert /config et le bandeau UI."""
    if compte and compte.get("host"):
        return {"configure": True, "fournisseur": "imap", "hote": compte["host"],
                "utilisateur": _masquer(compte.get("utilisateur", "")),
                "message": f"Boîte IMAP réelle ({compte['host']}), lecture seule."}
    return {"configure": False, "fournisseur": "mock",
            "message": "Aucun compte connecté : boîte SIMULÉE (mock), aucune connexion réseau."}


def _masquer(adresse: str) -> str:
    """a***@domaine.fr — assez pour reconnaître, pas assez pour fuiter."""
    if "@" not in adresse:
        return "***"
    avant, apres = adresse.split("@", 1)
    return (avant[:1] + "***") + "@" + apres
