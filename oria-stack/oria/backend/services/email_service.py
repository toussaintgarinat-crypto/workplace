"""
Service d'envoi d'emails transactionnels (smtplib).
Variables d'env: SMTP_HOST, SMTP_PORT (def 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
Si SMTP_HOST est vide, log uniquement (mode dev).
"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "noreply@oria.local")
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER)


def send_email(to: str, subject: str, body_html: str, body_text: str = "") -> bool:
    if not EMAIL_ENABLED:
        logger.info(f"[EMAIL SIMULÉ] To: {to} | Subject: {subject}")
        return True
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        if body_text:
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, to, msg.as_string())
        logger.info(f"Email envoyé à {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi email à {to}: {e}")
        return False
