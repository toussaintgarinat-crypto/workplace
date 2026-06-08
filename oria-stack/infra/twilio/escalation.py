"""
Service d'escalade SMS/Voice Twilio — Sprint 91.

Endpoints :
  POST /escalate          Reçoit une alerte, envoie SMS si severity=critical
  POST /oncall/ack        Marque l'alerte comme acquittée
  GET  /oncall/status     Statut astreinte en cours

Variables d'environnement :
  TWILIO_ACCOUNT_SID        SID du compte Twilio
  TWILIO_AUTH_TOKEN         Auth token Twilio
  TWILIO_FROM_NUMBER        Numéro Twilio expéditeur (ex: +33XXXXXXXXX)
  ONCALL_PHONE_NUMBER       Numéro de l'astreinte
  ESCALATION_TIMEOUT_MINUTES Délai avant appel vocal si SMS non ack (défaut: 10)
  ACK_TOKEN                 Token secret pour POST /oncall/ack
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ONCALL_PHONE_NUMBER = os.getenv("ONCALL_PHONE_NUMBER", "")
ESCALATION_TIMEOUT_MINUTES = int(os.getenv("ESCALATION_TIMEOUT_MINUTES", "10"))
ACK_TOKEN = os.getenv("ACK_TOKEN", "")

if not TWILIO_ACCOUNT_SID:
    logger.warning(
        "TWILIO_ACCOUNT_SID absent — mode test activé, aucun SMS/appel ne sera envoyé."
    )

# ── État en mémoire ──────────────────────────────────────────────────────────

@dataclass
class PendingAlert:
    alert_id: str
    severity: str
    message: str
    service: str
    created_at: float = field(default_factory=time.time)
    sms_sent_at: Optional[float] = None
    voice_sent_at: Optional[float] = None
    acknowledged: bool = False
    ack_at: Optional[float] = None


# Une seule alerte en cours (simplicité mono-astreinte)
_current_alert: Optional[PendingAlert] = None
_alert_lock = asyncio.Lock()

# ── Twilio helpers (httpx, pas le SDK officiel) ───────────────────────────────

TWILIO_BASE = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}"


def _twilio_auth() -> tuple[str, str]:
    return (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


async def _send_sms(to: str, body: str) -> bool:
    """Envoie un SMS via l'API REST Twilio. Retourne True si succès."""
    if not TWILIO_ACCOUNT_SID:
        logger.info("[TEST] SMS simulé vers %s : %s", to, body)
        return True

    url = f"{TWILIO_BASE}/Messages.json"
    payload = {
        "To": to,
        "From": TWILIO_FROM_NUMBER,
        "Body": body,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, data=payload, auth=_twilio_auth())
        if r.is_success:
            sid = r.json().get("sid", "?")
            logger.info("SMS envoyé (SID=%s) vers %s", sid, to)
            return True
        logger.error("SMS Twilio échoué : %s — %s", r.status_code, r.text)
        return False
    except Exception as exc:
        logger.exception("Erreur envoi SMS Twilio : %s", exc)
        return False


async def _make_voice_call(to: str, message: str) -> bool:
    """
    Lance un appel vocal via Twilio avec un TwiML inline.
    Le texte est lu via TTS Polly.
    """
    if not TWILIO_ACCOUNT_SID:
        logger.info("[TEST] Appel simulé vers %s : %s", to, message)
        return True

    twiml = (
        f'<Response><Say language="fr-FR" voice="Polly.Lea">'
        f"{message}"
        f"</Say><Pause length=\"2\"/>"
        f'<Say language="fr-FR" voice="Polly.Lea">Fin du message.</Say></Response>'
    )
    url = f"{TWILIO_BASE}/Calls.json"
    # TwiML passé en URL data: on utilise un TwiML Bin ou un endpoint inline
    # Ici on passe le TwiML directement via Twiml parameter (API moderne)
    payload = {
        "To": to,
        "From": TWILIO_FROM_NUMBER,
        "Twiml": twiml,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, data=payload, auth=_twilio_auth())
        if r.is_success:
            sid = r.json().get("sid", "?")
            logger.info("Appel vocal lancé (SID=%s) vers %s", sid, to)
            return True
        logger.error("Appel Twilio échoué : %s — %s", r.status_code, r.text)
        return False
    except Exception as exc:
        logger.exception("Erreur appel vocal Twilio : %s", exc)
        return False


# ── Escalade scheduler ────────────────────────────────────────────────────────

async def _check_escalation() -> None:
    """
    Tâche APScheduler : si l'alerte critique n'est pas acquittée après
    ESCALATION_TIMEOUT_MINUTES, déclenche un appel vocal.
    """
    global _current_alert
    async with _alert_lock:
        alert = _current_alert
        if alert is None or alert.acknowledged or alert.severity != "critical":
            return

        elapsed = time.time() - (alert.sms_sent_at or alert.created_at)
        timeout_s = ESCALATION_TIMEOUT_MINUTES * 60

        if elapsed >= timeout_s and alert.voice_sent_at is None:
            logger.warning(
                "Alerte %s non acquittée après %d min — appel vocal.",
                alert.alert_id,
                ESCALATION_TIMEOUT_MINUTES,
            )
            voice_msg = (
                f"Alerte critique non acquittée sur {alert.service}. "
                f"{alert.message}. "
                f"Veuillez acquitter immédiatement."
            )
            sent = await _make_voice_call(ONCALL_PHONE_NUMBER, voice_msg)
            if sent:
                alert.voice_sent_at = time.time()


# ── Lifespan ──────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        _check_escalation,
        "interval",
        minutes=1,
        id="escalation_check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler d'escalade démarré (vérification toutes les 60s).")
    yield
    scheduler.shutdown(wait=False)


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Escalation Service",
    description="Service d'escalade SMS/Voice Twilio — S91",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Schémas ───────────────────────────────────────────────────────────────────

class AlertPayload(BaseModel):
    severity: str  # "critical" | "warning" | "info"
    message: str
    service: str
    alert_id: Optional[str] = None


class AckPayload(BaseModel):
    alert_id: Optional[str] = None
    token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/escalate", status_code=status.HTTP_202_ACCEPTED)
async def escalate(payload: AlertPayload) -> dict:
    """
    Reçoit une alerte.
    - severity=critical → SMS immédiat + escalade voix si non-ack après timeout.
    - Autres sévérités → log uniquement.
    """
    global _current_alert

    import uuid
    alert_id = payload.alert_id or str(uuid.uuid4())

    logger.info(
        "Alerte reçue — id=%s severity=%s service=%s : %s",
        alert_id, payload.severity, payload.service, payload.message,
    )

    if payload.severity != "critical":
        return {"status": "logged", "alert_id": alert_id, "action": "none"}

    if not ONCALL_PHONE_NUMBER:
        logger.warning("ONCALL_PHONE_NUMBER non défini — SMS non envoyé.")
        return {"status": "skipped", "alert_id": alert_id, "reason": "no phone configured"}

    sms_body = (
        f"[ALERTE CRITIQUE] {payload.service}\n"
        f"{payload.message}\n"
        f"ID: {alert_id}"
    )
    sent = await _send_sms(ONCALL_PHONE_NUMBER, sms_body)

    async with _alert_lock:
        _current_alert = PendingAlert(
            alert_id=alert_id,
            severity=payload.severity,
            message=payload.message,
            service=payload.service,
            sms_sent_at=time.time() if sent else None,
        )

    return {
        "status": "escalated",
        "alert_id": alert_id,
        "sms_sent": sent,
        "voice_escalation_in_minutes": ESCALATION_TIMEOUT_MINUTES,
    }


@app.post("/oncall/ack", status_code=status.HTTP_200_OK)
async def ack_alert(payload: AckPayload) -> dict:
    """
    Acquitte l'alerte en cours (stoppe l'escalade voix).
    Nécessite le token ACK_TOKEN.
    """
    global _current_alert

    if ACK_TOKEN and payload.token != ACK_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token invalide.")

    async with _alert_lock:
        alert = _current_alert
        if alert is None:
            return {"status": "no_active_alert"}

        if payload.alert_id and alert.alert_id != payload.alert_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alerte '{payload.alert_id}' introuvable.",
            )

        alert.acknowledged = True
        alert.ack_at = time.time()
        logger.info("Alerte %s acquittée à t=%.0f", alert.alert_id, alert.ack_at)

    return {"status": "acknowledged", "alert_id": alert.alert_id}


@app.get("/oncall/status")
async def oncall_status() -> dict:
    """Retourne le statut de l'astreinte et de l'alerte en cours."""
    async with _alert_lock:
        alert = _current_alert

    if alert is None:
        return {
            "active_alert": None,
            "status": "idle",
        }

    elapsed = int(time.time() - alert.created_at)
    timeout_s = ESCALATION_TIMEOUT_MINUTES * 60

    if alert.acknowledged:
        state = "acknowledged"
    elif alert.voice_sent_at is not None:
        state = "voice_escalated"
    elif alert.sms_sent_at is not None:
        remaining = max(0, timeout_s - int(time.time() - alert.sms_sent_at))
        state = f"sms_sent (voice in {remaining}s)"
    else:
        state = "pending"

    return {
        "active_alert": {
            "alert_id": alert.alert_id,
            "severity": alert.severity,
            "service": alert.service,
            "message": alert.message,
            "created_at": alert.created_at,
            "elapsed_seconds": elapsed,
            "sms_sent": alert.sms_sent_at is not None,
            "voice_sent": alert.voice_sent_at is not None,
            "acknowledged": alert.acknowledged,
            "ack_at": alert.ack_at,
        },
        "status": state,
        "escalation_timeout_minutes": ESCALATION_TIMEOUT_MINUTES,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "twilio_configured": bool(TWILIO_ACCOUNT_SID)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("escalation:app", host="0.0.0.0", port=9001, reload=False)
