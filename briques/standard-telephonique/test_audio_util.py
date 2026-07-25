"""Tests audio_util : conversion WAV ↔ rtc.AudioFrame, sans connexion réseau."""
import io
import wave

from livekit import rtc

import audio_util


def _wav_de_test(sample_rate: int = 22050, num_channels: int = 1, duree_s: float = 0.5) -> bytes:
    """Construit un WAV silencieux en mémoire pour les tests (pas de fichier disque)."""
    n_samples = int(sample_rate * duree_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_samples * num_channels)
    return buf.getvalue()


def test_wav_bytes_to_audio_frames_parametres_corrects():
    wav = _wav_de_test(sample_rate=22050, num_channels=1, duree_s=0.5)
    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    assert sample_rate == 22050
    assert num_channels == 1
    assert len(frames) > 0
    assert all(isinstance(f, rtc.AudioFrame) for f in frames)


def test_wav_bytes_to_audio_frames_couvre_toute_la_duree():
    wav = _wav_de_test(sample_rate=16000, num_channels=1, duree_s=1.0)
    sample_rate, _, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    total_samples = sum(f.samples_per_channel for f in frames)
    # 1.0s à 16000Hz = 16000 échantillons — tolérance de +/- 1 frame (arrondi du dernier bloc)
    assert abs(total_samples - 16000) <= (0.020 * sample_rate)


def test_pcm_chunks_to_wav_bytes_roundtrip():
    wav = _wav_de_test(sample_rate=48000, num_channels=1, duree_s=0.2)
    sample_rate, num_channels, frames = audio_util.wav_bytes_to_audio_frames(wav, frame_ms=20)
    chunks = [bytes(f.data) for f in frames]
    rebuilt = audio_util.pcm_chunks_to_wav_bytes(chunks, sample_rate, num_channels)
    with wave.open(io.BytesIO(rebuilt), "rb") as w:
        assert w.getframerate() == sample_rate
        assert w.getnchannels() == num_channels
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0
