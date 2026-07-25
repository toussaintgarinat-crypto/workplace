"""Worker livekit-agents — décroche chaque appel SIP entrant (dispatch individuelle
`tel-*`, cf. Task 1), joue le menu, écoute la touche DTMF, enregistre un message
vocal (toutes les options tombent aujourd'hui sur le répondeur générique), le
transcrit, et notifie Telegram.

Dispatch automatique : aucun `agent_name` n'est fixé dans WorkerOptions, donc ce
worker rejoint AUTOMATIQUEMENT chaque nouvelle room du serveur LiveKit dédié
(cf. sip-stack/roomkit-visio/compose.override.yml — ce LiveKit n'est utilisé QUE par
ce chantier, l'auto-dispatch global est donc sans risque)."""
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from livekit import agents, rtc
from livekit.agents import JobContext, WorkerOptions, cli

import audio_util
import menu
import messages_store
import notifier
import transcription_client
import voix_client

logger = logging.getLogger("standard-telephonique.agent")
logging.basicConfig(level=logging.INFO)


async def _jouer_texte(room: rtc.Room, texte: str) -> None:
    """Synthétise `texte` (briques/voix) et le joue dans la room. Repli honnête : si
    la synthèse échoue, on ne joue rien plutôt que de faire planter l'appel."""
    wav = await voix_client.synthetiser(texte)
    if wav is None:
        logger.warning("Synthèse indisponible, menu non joué : %r", texte[:50])
        return

    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav)
    source = rtc.AudioSource(sample_rate=sample_rate, num_channels=num_channels)
    track = rtc.LocalAudioTrack.create_audio_track("menu", source)
    publication = await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    try:
        for frame in frames:
            await source.capture_frame(frame)
        await source.wait_for_playout()
    finally:
        await room.local_participant.unpublish_track(publication.sid)
        await source.aclose()


async def _attendre_choix(queue: "asyncio.Queue[str]", timeout_s: float) -> str | None:
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None


async def _enregistrer_message(track: rtc.Track, digit_queue: "asyncio.Queue[str]",
                               duree_max_s: float) -> tuple[bytes, int, int, float]:
    """Enregistre l'audio entrant jusqu'à `#`, raccroché, ou `duree_max_s` écoulées.
    Retourne (wav_bytes, sample_rate, num_channels, duree_s)."""
    sample_rate, num_channels = 48000, 1
    stream = rtc.AudioStream(track, sample_rate=sample_rate, num_channels=num_channels)
    chunks: list[bytes] = []
    debut = time.monotonic()

    async def _collecter() -> None:
        async for ev in stream:
            chunks.append(bytes(ev.frame.data))

    tache_collecte = asyncio.create_task(_collecter())

    async def _attendre_diese() -> None:
        while True:
            digit = await digit_queue.get()
            if digit == "#":
                return

    tache_arret = asyncio.create_task(_attendre_diese())
    tache_sleep = asyncio.create_task(asyncio.sleep(duree_max_s))
    try:
        await asyncio.wait([tache_collecte, tache_arret, tache_sleep],
                           return_when=asyncio.FIRST_COMPLETED)
    finally:
        tache_collecte.cancel()
        tache_arret.cancel()
        tache_sleep.cancel()
        await asyncio.gather(tache_collecte, tache_arret, tache_sleep, return_exceptions=True)
        await stream.aclose()

    duree_s = time.monotonic() - debut
    wav = audio_util.pcm_chunks_to_wav_bytes(chunks, sample_rate, num_channels)
    return wav, sample_rate, num_channels, duree_s


async def _gerer_appel(ctx: JobContext) -> None:
    room = ctx.room
    digit_queue: "asyncio.Queue[str]" = asyncio.Queue()

    @room.on("sip_dtmf_received")
    def _on_dtmf(dtmf: rtc.SipDTMF) -> None:
        digit_queue.put_nowait(dtmf.digit)

    track_appelant: rtc.Track | None = None
    track_pret = asyncio.Event()

    @room.on("track_subscribed")
    def _on_track_subscribed(track: rtc.Track, publication, participant) -> None:
        nonlocal track_appelant
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP and \
                track.kind == rtc.TrackKind.KIND_AUDIO:
            track_appelant = track
            track_pret.set()

    participant = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
    logger.info("Participant SIP connecté : %s", participant.identity)

    await asyncio.wait_for(track_pret.wait(), timeout=10.0)

    # Menu, avec une répétition si aucune touche n'est pressée
    await _jouer_texte(room, menu.TEXTE_MENU)
    choix = await _attendre_choix(digit_queue, menu.DUREE_ATTENTE_DTMF_S)
    if choix is None:
        await _jouer_texte(room, menu.TEXTE_MENU)
        choix = await _attendre_choix(digit_queue, menu.DUREE_ATTENTE_DTMF_S)

    logger.info("Option choisie : %r", choix)

    # Toutes les options tombent aujourd'hui sur le répondeur générique.
    await _jouer_texte(room, menu.TEXTE_BIP_INTRODUCTION)
    wav, sample_rate, num_channels, duree_s = await _enregistrer_message(
        track_appelant, digit_queue, menu.DUREE_MAX_ENREGISTREMENT_S
    )

    if duree_s < 0.5:
        logger.info("Enregistrement vide (%.1fs), rien à faire.", duree_s)
        return

    messages_dir = Path(os.getenv("MESSAGES_DIR", "/data/audio"))
    messages_dir.mkdir(parents=True, exist_ok=True)
    audio_path = messages_dir / f"{uuid.uuid4()}.wav"
    audio_path.write_bytes(wav)

    texte = await transcription_client.transcrire(wav)

    db_path = os.getenv("MESSAGES_DB", "/data/messages.db")
    messages_store.enregistrer(db_path, option=choix, audio_path=str(audio_path),
                               duree_s=duree_s, texte=texte)

    resume = texte if texte else "(transcription indisponible)"
    option_txt = choix if choix else "aucune (délai dépassé)"
    await notifier.notifier(
        f"📞 Nouveau message vocal — option {option_txt} ({duree_s:.0f}s)\n{resume}"
    )


async def entrypoint(ctx: JobContext) -> None:
    logger.info("Connexion à la room %s", ctx.room.name)
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)
    try:
        await _gerer_appel(ctx)
    except Exception:
        logger.exception("Erreur pendant la gestion de l'appel")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
