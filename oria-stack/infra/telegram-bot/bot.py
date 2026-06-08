"""
Telegram bot S91 — commandes entrantes pour astreinte et supervision.

Variables d'environnement requises :
  TELEGRAM_BOT_TOKEN          Token du bot BotFather
  TELEGRAM_ADMIN_CHAT_ID      Chat ID autorisé pour /drill et /silence
  ASSISTANT_URL               Base URL du service assistant (sans port)
  MEMPALACE_URL               Base URL de MemPalace (sans port)
  ORIA_URL                    Base URL d'Oria (sans port)
  ONCALL_NAME                 Nom de l'astreinte (défaut: Toussaint)
  RUNBOOKS_DIR                Répertoire des runbooks (défaut: /app/runbooks)
  CHAOS_SCRIPTS_DIR           Répertoire des scripts chaos (défaut: /app/chaos)
"""

import asyncio
import glob
import logging
import os
import subprocess
import time
from pathlib import Path

import httpx
from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, TypeHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
ASSISTANT_URL = os.getenv("ASSISTANT_URL", "http://localhost")
MEMPALACE_URL = os.getenv("MEMPALACE_URL", "http://localhost")
ORIA_URL = os.getenv("ORIA_URL", "http://localhost")
ONCALL_NAME = os.getenv("ONCALL_NAME", "Toussaint")
RUNBOOKS_DIR = Path(os.getenv("RUNBOOKS_DIR", "/app/runbooks"))
CHAOS_SCRIPTS_DIR = Path(os.getenv("CHAOS_SCRIPTS_DIR", "/app/chaos"))
HEALTH_PORT = int(os.getenv("TELEGRAM_HEALTH_PORT", "9090"))

# État partagé pour /health — alimenté par TypeHandler ci-dessous
START_TS = time.time()
LAST_UPDATE_TS: float = 0.0  # 0 = aucun update reçu pour l'instant

SERVICES = [
    ("assistant", f"{ASSISTANT_URL}:8000/health"),
    ("mempalace", f"{MEMPALACE_URL}:8100/health"),
    ("oria", f"{ORIA_URL}:8200/health"),
    ("qdrant", "http://localhost:6334/"),
    ("minio", "http://localhost:9100/minio/health/live"),
]

SILENCE_FILE = Path("/tmp/silence_until")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin(update: Update) -> bool:
    """Retourne True si le message provient du chat admin configuré."""
    if not ADMIN_CHAT_ID:
        return False
    return str(update.effective_chat.id) == str(ADMIN_CHAT_ID)


def _is_silenced() -> bool:
    """Retourne True si les alertes sont actuellement silencées."""
    if not SILENCE_FILE.exists():
        return False
    try:
        until = float(SILENCE_FILE.read_text().strip())
        if time.time() < until:
            return True
        SILENCE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return False


async def _check_http(name: str, url: str) -> tuple[str, str]:
    """
    Vérifie un endpoint HTTP.
    Retourne (name, emoji) : 🟢 200, 🟡 non-200, 🔴 injoignable.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
        if r.is_success:
            return name, "🟢"
        return name, f"🟡 HTTP {r.status_code}"
    except Exception as exc:
        logger.warning("Health check failed for %s: %s", name, exc)
        return name, "🔴"


async def _check_postgres() -> tuple[str, str]:
    """Vérifie PostgreSQL via pg_isready si disponible, sinon connexion TCP."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_isready",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5)
        return "postgres", "🟢" if proc.returncode == 0 else "🔴"
    except FileNotFoundError:
        # pg_isready absent : tentative TCP directe
        try:
            pg_host = os.getenv("PGHOST", "localhost")
            pg_port = int(os.getenv("PGPORT", "5432"))
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(pg_host, pg_port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return "postgres", "🟢"
        except Exception:
            return "postgres", "🔴"
    except Exception as exc:
        logger.warning("Postgres check error: %s", exc)
        return "postgres", "🔴"


def _log_command(update: Update, command: str) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(
        "Command /%s from user=%s (id=%s) chat=%s",
        command,
        user.username or user.first_name,
        user.id,
        chat_id,
    )


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "start")
    text = (
        "*Bot d'astreinte — commandes disponibles*\n\n"
        "/status — Santé de tous les services\n"
        "/degraded — Mode dégradé des services applicatifs\n"
        "/runbook \\<id\\> — Affiche un runbook \\(ex: /runbook postgres\\-failover\\)\n"
        "/oncall — Qui est d'astreinte ?\n"
        "\n*Commandes admin uniquement :*\n"
        "/drill \\<composant\\> — Lance un scénario de chaos\n"
        "/silence \\<durée\\> — Silences les alertes \\(ex: 30m, 2h\\)\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "status")
    await update.message.reply_text("⏳ Vérification en cours…")

    checks = [_check_http(name, url) for name, url in SERVICES]
    checks.append(_check_postgres())  # type: ignore[arg-type]
    results = await asyncio.gather(*checks)

    lines = ["*État des services*\n"]
    for name, icon in results:
        lines.append(f"{icon}  `{name}`")

    if _is_silenced():
        lines.append("\n_⏸ Alertes silencées_")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_degraded(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "degraded")
    await update.message.reply_text("⏳ Récupération du mode dégradé…")

    targets = [
        ("assistant", f"{ASSISTANT_URL}:8000/admin/degraded"),
        ("mempalace", f"{MEMPALACE_URL}:8100/admin/degraded"),
        ("oria", f"{ORIA_URL}:8200/admin/degraded"),
    ]

    lines = ["*Mode dégradé par service*\n"]
    async with httpx.AsyncClient(timeout=6) as client:
        for name, url in targets:
            try:
                r = await client.get(url)
                if r.is_success:
                    data = r.json()
                    # Normalise : l'endpoint retourne {"components": {...}} ou directement {...}
                    components = data.get("components", data)
                    degraded = [k for k, v in components.items() if v]
                    if degraded:
                        icon = "🟡"
                        detail = ", ".join(degraded)
                    else:
                        icon = "🟢"
                        detail = "nominal"
                    lines.append(f"{icon}  *{name}* : {detail}")
                else:
                    lines.append(f"🔴  *{name}* : HTTP {r.status_code}")
            except Exception as exc:
                logger.warning("Degraded check failed for %s: %s", name, exc)
                lines.append(f"🔴  *{name}* : injoignable")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_runbook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "runbook")
    if not context.args:
        await update.message.reply_text(
            "Usage : /runbook <id>\nEx : /runbook postgres-failover\n\n"
            f"Runbooks disponibles : {', '.join(_list_runbooks())}"
        )
        return

    runbook_id = context.args[0].lower().strip()
    pattern = str(RUNBOOKS_DIR / f"{runbook_id}*.md")
    matches = glob.glob(pattern)

    if not matches:
        # Recherche partielle
        pattern_partial = str(RUNBOOKS_DIR / f"*{runbook_id}*.md")
        matches = glob.glob(pattern_partial)

    if not matches:
        available = ", ".join(_list_runbooks()) or "aucun"
        await update.message.reply_text(
            f"Runbook '{runbook_id}' introuvable.\nDisponibles : {available}"
        )
        return

    path = Path(matches[0])
    content = path.read_text(encoding="utf-8")

    MAX_CHARS = 3000
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS] + f"\n\n… _(tronqué à {MAX_CHARS} chars)_"

    header = f"*Runbook : {path.stem}*\n\n"
    await update.message.reply_text(
        header + content,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


def _list_runbooks() -> list[str]:
    if not RUNBOOKS_DIR.exists():
        return []
    return [p.stem for p in sorted(RUNBOOKS_DIR.glob("*.md"))]


async def cmd_drill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "drill")
    if not _is_admin(update):
        await update.message.reply_text("⛔ Commande réservée à l'administrateur.")
        return

    if not context.args:
        await update.message.reply_text("Usage : /drill <composant>\nEx : /drill postgres")
        return

    component = context.args[0].lower().strip()
    script = CHAOS_SCRIPTS_DIR / "random-failure.sh"

    if not script.exists():
        await update.message.reply_text(
            f"⚠️ Script chaos introuvable : {script}\n"
            "Déposez random-failure.sh dans CHAOS_SCRIPTS_DIR."
        )
        return

    await update.message.reply_text(f"🔥 Lancement du drill : `{component}`", parse_mode=ParseMode.MARKDOWN_V2)

    try:
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(script),
            "--scenario",
            component,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await update.message.reply_text("⏱ Drill timeout (60s) — processus tué.")
            return

        output = stdout.decode(errors="replace")[:1500] if stdout else "(pas de sortie)"
        rc = proc.returncode
        icon = "✅" if rc == 0 else "❌"
        await update.message.reply_text(
            f"{icon} Drill terminé (rc={rc})\n```\n{output}\n```",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as exc:
        logger.exception("Drill error for component %s", component)
        await update.message.reply_text(f"❌ Erreur lors du drill : {exc}")


async def cmd_silence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "silence")
    if not _is_admin(update):
        await update.message.reply_text("⛔ Commande réservée à l'administrateur.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage : /silence <durée>\nEx : /silence 30m  ou  /silence 2h"
        )
        return

    raw = context.args[0].lower().strip()
    seconds = _parse_duration(raw)
    if seconds is None:
        await update.message.reply_text(
            f"Format invalide : '{raw}'. Utilisez Xs, Xm ou Xh."
        )
        return

    until = time.time() + seconds
    SILENCE_FILE.write_text(str(until))
    logger.info("Alertes silencées pendant %s secondes par admin %s", seconds, update.effective_user.id)
    await update.message.reply_text(f"⏸ Alertes silencées pendant *{raw}*.", parse_mode=ParseMode.MARKDOWN_V2)


def _parse_duration(s: str) -> int | None:
    """Convertit '30m', '2h', '90s' en secondes. Retourne None si invalide."""
    multipliers = {"s": 1, "m": 60, "h": 3600}
    if s and s[-1] in multipliers:
        try:
            return int(s[:-1]) * multipliers[s[-1]]
        except ValueError:
            pass
    # Tente un entier pur (secondes)
    try:
        return int(s)
    except ValueError:
        return None


async def cmd_oncall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_command(update, "oncall")
    silenced = _is_silenced()
    silence_note = ""
    if silenced:
        try:
            until = float(SILENCE_FILE.read_text().strip())
            remaining = max(0, int(until - time.time()))
            h, rem = divmod(remaining, 3600)
            m, s = divmod(rem, 60)
            parts = []
            if h:
                parts.append(f"{h}h")
            if m:
                parts.append(f"{m}m")
            if s or not parts:
                parts.append(f"{s}s")
            silence_note = f"\n⏸ _Alertes silencées encore {"".join(parts)}_"
        except Exception:
            silence_note = "\n⏸ _Alertes silencées_"

    text = (
        f"📟 *Astreinte en cours*\n\n"
        f"👤 {ONCALL_NAME}"
        f"{silence_note}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


# ── Health endpoint (aiohttp) ─────────────────────────────────────────────────

async def _track_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global LAST_UPDATE_TS
    LAST_UPDATE_TS = time.time()


async def health_handler(request: web.Request) -> web.Response:
    """GET /health — vérifie que l'API Telegram répond.

    Retour 200 + JSON {status, uptime_seconds, seconds_since_last_update}.
    Retour 503 si bot.get_me() échoue (token invalide, réseau coupé).
    """
    bot = request.app["bot"]
    now = time.time()
    payload = {
        "uptime_seconds": int(now - START_TS),
        "seconds_since_last_update": int(now - LAST_UPDATE_TS) if LAST_UPDATE_TS else None,
    }
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=3)
        payload["status"] = "ok"
        payload["bot"] = me.username
        return web.json_response(payload)
    except Exception as exc:
        payload["status"] = "error"
        payload["error"] = str(exc)
        logger.warning("Health check failed: %s", exc)
        return web.json_response(payload, status=503)


async def _start_health_server(application: Application) -> None:
    """post_init hook : démarre aiohttp en parallèle du polling Telegram."""
    aio_app = web.Application()
    aio_app["bot"] = application.bot
    aio_app.router.add_get("/health", health_handler)
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HEALTH_PORT)
    await site.start()
    logger.info("Endpoint /health en écoute sur :%d", HEALTH_PORT)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Démarrage du bot Telegram (polling)…")
    if not ADMIN_CHAT_ID:
        logger.warning(
            "TELEGRAM_ADMIN_CHAT_ID non défini — commandes /drill et /silence désactivées."
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_start_health_server)
        .build()
    )

    # Groupe -1 : tracker exécuté avant les handlers de commandes
    app.add_handler(TypeHandler(Update, _track_update), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("degraded", cmd_degraded))
    app.add_handler(CommandHandler("runbook", cmd_runbook))
    app.add_handler(CommandHandler("drill", cmd_drill))
    app.add_handler(CommandHandler("silence", cmd_silence))
    app.add_handler(CommandHandler("oncall", cmd_oncall))

    logger.info("Bot prêt. En attente de commandes…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
