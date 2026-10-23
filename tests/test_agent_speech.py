"""Speech to text for the mic button, with OpenRouter faked: no network, no cost."""

import io
import wave

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.agents import speech
from apps.agents.api import views
from apps.agents.api.serializers import MAX_AUDIO_BYTES


def wav_bytes(seconds: float = 0.1) -> bytes:
    """A real (silent) 16 kHz mono WAV recording, like the browser sends."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(16_000)
        recording.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buffer.getvalue()


def upload(client, content: bytes, name: str = "speech.wav"):
    audio = SimpleUploadedFile(name, content, content_type="audio/wav")
    return client.post("/api/agent/transcribe/", {"audio": audio})


@pytest.fixture
def transcribed(monkeypatch):
    """Replace the speech service: record what it received, answer with fixed text."""
    received = []

    def fake_transcribe(audio: bytes) -> str:
        received.append(audio)
        return "یه گوشی سامسونگ"

    monkeypatch.setattr(views, "transcribe", fake_transcribe)
    return received


# --- The OpenRouter call -----------------------------------------------------------------


def test_transcribe_asks_whisper_in_persian(monkeypatch, settings):
    settings.OPENROUTER_API_KEY = "sk-test"
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return httpx.Response(200, json={"text": "  سلام  "}, request=httpx.Request("POST", url))

    monkeypatch.setattr(speech.httpx, "post", fake_post)

    assert speech.transcribe(b"RIFF...") == "سلام"
    assert sent["url"] == speech.TRANSCRIBE_URL
    assert sent["headers"] == {"Authorization": "Bearer sk-test"}
    assert sent["data"] == {"model": speech.TRANSCRIBE_MODEL, "language": "fa"}
    assert sent["files"]["file"] == ("speech.wav", b"RIFF...", "audio/wav")


def raising(error: Exception):
    """A fake httpx.post that fails the way a real network call can."""

    def post(url, **kwargs):
        raise error

    return post


def server_error(url, **kwargs):
    return httpx.Response(500, request=httpx.Request("POST", url))


@pytest.mark.parametrize(
    "failure",
    [server_error, raising(httpx.ConnectError("no route")), raising(httpx.ReadTimeout("slow"))],
    ids=["server error", "unreachable", "timeout"],
)
def test_transcribe_failures_become_one_error_type(monkeypatch, failure):
    monkeypatch.setattr(speech.httpx, "post", failure)
    with pytest.raises(speech.TranscriptionError):
        speech.transcribe(b"RIFF...")


# --- The endpoint ------------------------------------------------------------------------


def test_a_recording_comes_back_as_text(client, transcribed):
    recording = wav_bytes()
    response = upload(client, recording)

    assert (response.status_code, response.json()) == (200, {"text": "یه گوشی سامسونگ"})
    assert transcribed == [recording]


@pytest.mark.parametrize(
    "content",
    [b"", b"not audio at all", b"ID3\x04 an mp3 file"],
    ids=["empty", "junk", "not wav"],
)
def test_only_wav_recordings_reach_the_paid_service(client, transcribed, content):
    assert upload(client, content).status_code == 400
    assert transcribed == []


def test_too_long_recordings_are_refused(client, transcribed):
    too_long = wav_bytes() + b"\x00" * MAX_AUDIO_BYTES
    assert upload(client, too_long).status_code == 400
    assert transcribed == []


def test_service_failure_is_a_friendly_error(client, monkeypatch):
    def broken(audio: bytes) -> str:
        raise speech.TranscriptionError("OpenRouter is down")

    monkeypatch.setattr(views, "transcribe", broken)
    response = upload(client, wav_bytes())

    assert response.status_code == 502
    assert "OpenRouter" not in response.json()["detail"]  # no internals shown to users


def test_transcription_is_rate_limited(client, transcribed):
    recording = wav_bytes()
    codes = [upload(client, recording).status_code for _ in range(61)]
    assert codes == [200] * 60 + [429]
