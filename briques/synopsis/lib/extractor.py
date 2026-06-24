"""YouTube Transcript Extractor — adapted for Synopsis."""

import logging
import re
import time
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript,
)
import httpx

logger = logging.getLogger(__name__)


def extract_youtube_id(url: str) -> Optional[str]:
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube-nocookie\.com/embed/)([A-Za-z0-9_-]{11})',
        r'youtube\.com/shorts/([A-Za-z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def detect_channel(url: str) -> bool:
    return bool(re.search(r'youtube\.com/(@|channel/|c/)', url))


def get_video_title(video_id: str) -> str:
    try:
        r = httpx.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json", timeout=10)
        if r.status_code == 200:
            return r.json().get("title", f"Video {video_id}")
    except Exception:
        logger.debug("Could not fetch title for %s", video_id)
    return f"Video {video_id}"


def get_youtube_transcript(url: str, languages: list = None) -> dict:
    if languages is None:
        languages = ['fr', 'en', 'es', 'de', 'it', 'pt']

    if detect_channel(url):
        raise ValueError("Cette URL est une chaîne YouTube. Fournissez l'URL d'une vidéo.")

    video_id = extract_youtube_id(url)
    if not video_id:
        raise ValueError("URL YouTube invalide. Format: youtube.com/watch?v=ID ou youtu.be/ID")

    yt_api = YouTubeTranscriptApi()
    transcript_data = None
    original_lang = None

    for lang in languages:
        try:
            transcript = yt_api.fetch(video_id, languages=[lang])
            transcript_data = list(transcript)
            original_lang = lang
            break
        except Exception:
            continue

    if not transcript_data:
        try:
            transcript = yt_api.fetch(video_id)
            transcript_data = list(transcript)
            original_lang = getattr(transcript, 'language_code', 'en') or 'en'
        except TranscriptsDisabled:
            raise ValueError("Transcript désactivé sur cette vidéo YouTube")
        except NoTranscriptFound:
            raise ValueError("Aucun transcript disponible pour cette vidéo")
        except CouldNotRetrieveTranscript as e:
            if "403" in str(e):
                time.sleep(3)
                transcript = yt_api.fetch(video_id, languages=languages)
                transcript_data = list(transcript)
                original_lang = 'en'
            else:
                raise ValueError(f"Erreur transcript: {e}")

    if not transcript_data:
        raise ValueError("Transcript vide")

    formatted = [{'text': e.text, 'start': e.start, 'duration': e.duration} for e in transcript_data]
    last = formatted[-1]
    total_minutes = (last['start'] + last['duration']) / 60

    return {
        'video_id': video_id,
        'transcript': formatted,
        'language': original_lang or 'unknown',
        'title': get_video_title(video_id),
        'total_duration_minutes': total_minutes,
        'entries_count': len(formatted),
    }
