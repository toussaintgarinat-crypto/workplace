"""Conversion WAV ↔ rtc.AudioFrame — pure, sans connexion réseau LiveKit.

Le format audio interne de LiveKit est du PCM 16 bits signé entrelacé par canal
(cf. livekit.rtc.AudioFrame). On lit/écrit des fichiers WAV via le module stdlib
`wave`, qui utilise exactement ce même format — pas de dépendance supplémentaire.
"""
import io
import wave

from livekit import rtc


def wav_bytes_to_audio_frames(wav_bytes: bytes, frame_ms: int = 20) -> tuple[int, int, list[rtc.AudioFrame]]:
    """Découpe un WAV (mono ou stéréo, PCM 16 bits) en frames LiveKit de `frame_ms`
    millisecondes, prêtes à être poussées via `AudioSource.capture_frame`.

    Retourne (sample_rate, num_channels, frames) — sample_rate/num_channels sont ceux
    du fichier WAV lui-même (on ne suppose jamais un débit fixe : le moteur TTS peut
    changer de voix/modèle avec un débit différent)."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sample_rate = w.getframerate()
        num_channels = w.getnchannels()
        assert w.getsampwidth() == 2, "seul le PCM 16 bits est supporté"
        pcm = w.readframes(w.getnframes())

    samples_per_frame = max(1, int(sample_rate * frame_ms / 1000))
    bytes_per_sample_all_channels = 2 * num_channels
    bloc_octets = samples_per_frame * bytes_per_sample_all_channels

    frames: list[rtc.AudioFrame] = []
    for debut in range(0, len(pcm), bloc_octets):
        bloc = pcm[debut:debut + bloc_octets]
        if not bloc:
            continue
        n_samples = len(bloc) // bytes_per_sample_all_channels
        if n_samples == 0:
            continue
        frames.append(rtc.AudioFrame(
            data=bloc,
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=n_samples,
        ))
    return sample_rate, num_channels, frames


def pcm_chunks_to_wav_bytes(chunks: list[bytes], sample_rate: int, num_channels: int) -> bytes:
    """Concatène des morceaux de PCM 16 bits (ex. audio reçu d'un appelant) en un WAV
    complet. Utilisé pour sauvegarder l'enregistrement du répondeur."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"".join(chunks))
    return buf.getvalue()
