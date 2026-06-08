"""Envoi d'emails transactionnels — socle S130, étendu S22.

S130 : un seul email (code de suppression de venture), stdlib `smtplib` exécutée
hors boucle via `asyncio.to_thread`. S22 généralise :
- `send()` générique + templates (facture émise, relance impayée à 3 niveaux) ;
- **mot de passe SMTP résolu depuis le coffre chiffré** (`ProviderApiKeys`/`crypto`,
  comme la clé Stripe en S21) → repli env `SMTP_PASS`, jamais en clair, masqué en log ;
- `SMTP_STARTTLS` optionnel (relais interne/dev sans TLS).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import desc, select

from app.config import settings
from app.crypto import decrypt
from app.db import SessionLocal
from app.models import ProviderApiKeys

log = logging.getLogger("forge.email")


async def resolve_smtp_password() -> str:
    """Mot de passe SMTP : d'abord chiffré en base (`ProviderApiKeys` provider `smtp`),
    sinon repli env `SMTP_PASS`. Jamais loggé en clair. Une clé corrompue retombe sur l'env.
    """
    async with SessionLocal() as s:
        row = (await s.execute(
            select(ProviderApiKeys)
            .where(ProviderApiKeys.provider == "smtp")
            .order_by(desc(ProviderApiKeys.updated_at))
            .limit(1)
        )).scalar_one_or_none()
    if row and row.encrypted_key:
        try:
            return decrypt(row.encrypted_key)
        except Exception:  # noqa: BLE001 — repli env
            log.warning("Mot de passe SMTP en base illisible, repli sur l'env.")
    return settings.SMTP_PASS or ""


def _send_sync(to: str, subject: str, html: str, password: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or f'"Forge" <{settings.SMTP_USER}>'
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("Votre client mail ne supporte pas le HTML.")
    msg.add_alternative(html, subtype="html")

    if settings.SMTP_SECURE:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
    try:
        if not settings.SMTP_SECURE and settings.SMTP_STARTTLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, password)
        server.send_message(msg)
    finally:
        server.quit()


async def send(to: str, subject: str, html: str) -> None:
    """Envoi générique (mot de passe résolu au coffre). Lève si SMTP échoue."""
    if not to:
        raise ValueError("Destinataire email manquant.")
    password = await resolve_smtp_password()
    await asyncio.to_thread(_send_sync, to, subject, html, password)


# ── Gabarit commun ────────────────────────────────────────────────────────────

def _enveloppe(corps_html: str) -> str:
    return f"""
      <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;color:#1a1a1a">
        <h2 style="color:#6366f1">⚡ Forge</h2>
        {corps_html}
        <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
        <p style="color:#999;font-size:12px">Cet email vous est adressé dans le cadre de votre
        relation commerciale. Pour toute question, répondez simplement à ce message.</p>
      </div>
    """


def _eur(x: float | None) -> str:
    return f"{(x or 0):,.2f} €".replace(",", " ").replace(".", ",")


def template_facture_emise(*, client: str, numero: str, montant_ttc: float,
                           echeance: str = "") -> tuple[str, str]:
    """(sujet, html) de l'email d'émission d'une facture."""
    sujet = f"Votre facture {numero}"
    ech = f"<p>Échéance de paiement : <strong>{echeance}</strong>.</p>" if echeance else ""
    corps = f"""
      <p>Bonjour {client},</p>
      <p>Veuillez trouver votre facture <strong>{numero}</strong> d'un montant de
         <strong>{_eur(montant_ttc)} TTC</strong>.</p>
      {ech}
      <p>Nous vous remercions de votre confiance.</p>
    """
    return sujet, _enveloppe(corps)


# Niveaux de relance : J+7 courtois, J+15 ferme, J+30 mise en demeure douce.
RELANCE_NIVEAUX = {
    7: {
        "label": "J+7",
        "sujet": "Rappel — facture {numero} en attente de règlement",
        "intro": "Sauf erreur de notre part, la facture <strong>{numero}</strong> "
                 "({montant} TTC) reste à régler. Il s'agit peut-être d'un simple oubli.",
        "ton": "Nous vous remercions de bien vouloir procéder au règlement.",
    },
    15: {
        "label": "J+15",
        "sujet": "2e rappel — facture {numero} échue",
        "intro": "La facture <strong>{numero}</strong> ({montant} TTC) est échue depuis "
                 "plus de deux semaines et demeure impayée.",
        "ton": "Merci de régulariser cette situation dans les meilleurs délais.",
    },
    30: {
        "label": "J+30",
        "sujet": "Relance finale — facture {numero} impayée",
        "intro": "Malgré nos précédents rappels, la facture <strong>{numero}</strong> "
                 "({montant} TTC) reste impayée depuis plus de 30 jours.",
        "ton": "Sans règlement de votre part sous huitaine, nous serons contraints "
               "d'envisager les suites appropriées.",
    },
}


def template_relance(*, client: str, numero: str, montant_ttc: float, niveau: int) -> tuple[str, str]:
    """(sujet, html) d'une relance impayée pour le niveau donné (7/15/30)."""
    n = RELANCE_NIVEAUX[niveau]
    montant = _eur(montant_ttc)
    sujet = n["sujet"].format(numero=numero)
    corps = f"""
      <p>Bonjour {client},</p>
      <p>{n['intro'].format(numero=numero, montant=montant)}</p>
      <p>{n['ton']}</p>
    """
    return sujet, _enveloppe(corps)


async def send_venture_deletion_code(*, to: str, venture_name: str, code: str, expires_in: str) -> None:
    """Code de confirmation de suppression d'une venture (parité Bun, S130)."""
    subject = f"[Forge] Confirmation de suppression — {venture_name}"
    html = f"""
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
        <h2 style="color:#6366f1">⚡ Forge</h2>
        <p>Vous avez demandé la suppression de la venture <strong>{venture_name}</strong>.</p>
        <p>Voici votre code de confirmation :</p>
        <div style="font-size:36px;font-weight:700;letter-spacing:12px;text-align:center;padding:24px;background:#0f0f17;border-radius:12px;color:#818cf8;margin:24px 0">
          {code}
        </div>
        <p style="color:#888;font-size:13px">Ce code expire dans {expires_in}.<br>
        Si vous n'avez pas demandé cette suppression, ignorez cet email.</p>
        <hr style="border:none;border-top:1px solid #222;margin:24px 0">
        <p style="color:#555;font-size:12px">Cette action est <strong>irréversible</strong> — tous les pôles, sessions et données associés seront supprimés.</p>
      </div>
    """
    password = await resolve_smtp_password()
    await asyncio.to_thread(_send_sync, to, subject, html, password)
