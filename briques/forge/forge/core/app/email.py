"""Envoi d'emails transactionnels — portage de email/index.ts (S130).

Fidèle à nodemailer côté Bun : même config SMTP (env), même sujet/HTML. On
utilise la stdlib `smtplib` (zéro dépendance ajoutée), exécutée hors boucle
événementielle via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import settings


def _send_sync(to: str, subject: str, html: str) -> None:
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
        if not settings.SMTP_SECURE:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
    finally:
        server.quit()


async def send_venture_deletion_code(*, to: str, venture_name: str, code: str, expires_in: str) -> None:
    """Envoie le code de confirmation de suppression d'une venture (parité Bun)."""
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
    await asyncio.to_thread(_send_sync, to, subject, html)
