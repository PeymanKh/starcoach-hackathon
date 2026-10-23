"""Speech to text through OpenRouter's transcription API (Whisper)."""

import httpx
from django.conf import settings

TRANSCRIBE_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
TRANSCRIBE_MODEL = "openai/whisper-large-v3"
TIMEOUT_SECONDS = 20


class TranscriptionError(Exception):
    """The speech service failed or could not be reached."""


def transcribe(audio: bytes, language: str = "fa") -> str:
    """The text spoken in a WAV recording. Raises TranscriptionError if the service fails."""

    try:
        response = httpx.post(
            TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            data={"model": TRANSCRIBE_MODEL, "language": language},
            files={"file": ("speech.wav", audio, "audio/wav")},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise TranscriptionError(str(error)) from error
    return response.json().get("text", "").strip()
