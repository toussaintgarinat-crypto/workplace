"""Envoi d'email transactionnel (réinitialisation de mot de passe) — SMTP direct, propre à
cette brique. PAS un appel à la brique `mail` (6030) : celle-ci gère des boîtes personnelles
connectées, pas un envoi de service — la coupler ici casserait le motif « facile à sortir du
repo » de toute cette brique (cf. spec § contexte). Mode simulé si SMTP non configuré (dev/
test, aucun email ne part) ; erreur SMTP réelle propagée telle quelle si configuré."""
import os
import smtplib
from email.message import EmailMessage


def _config() -> dict | None:
    host = os.environ.get("JEU_FACTIONS_PUBLIC_SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("JEU_FACTIONS_PUBLIC_SMTP_PORT", "587")),
        "user": os.environ.get("JEU_FACTIONS_PUBLIC_SMTP_USER", ""),
        "password": os.environ.get("JEU_FACTIONS_PUBLIC_SMTP_PASSWORD", ""),
        "expediteur": os.environ.get("JEU_FACTIONS_PUBLIC_SMTP_FROM", ""),
    }


def envoyer(destinataire: str, sujet: str, corps: str) -> str:
    """Renvoie "envoye" ou "simule"."""
    config = _config()
    if not config:
        return "simule"
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = config["expediteur"] or config["user"]
    msg["To"] = destinataire
    msg.set_content(corps)
    with smtplib.SMTP(config["host"], config["port"], timeout=10) as s:
        s.starttls()
        if config["user"]:
            s.login(config["user"], config["password"])
        s.send_message(msg)
    return "envoye"
