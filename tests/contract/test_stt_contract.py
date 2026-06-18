"""Contract (LSP) tests for every speech-to-text adapter against the port.

Each adapter must be substitutable for the ``SpeechToText`` port: satisfy the
protocol shape, return a normalized :class:`Transcription`, and raise the typed
``SpeechToTextError`` on failure (never a provider-specific exception). The HTTP
backends are exercised with a fake ``urlopen``; faster-whisper with a fake model —
so the contract runs with no network, no models, and no heavy dependencies.
"""

from __future__ import annotations

import importlib.util
from urllib import request as urllib_request

import pytest

from vaivox.application.ports import SpeechToText, SpeechToTextError
from vaivox.domain.reconciliation.model import Transcription
from vaivox.infrastructure.config.settings import WhisperAttackConfiguration
from vaivox.infrastructure.stt.deepgram import DeepgramBackend
from vaivox.infrastructure.stt.elevenlabs import ElevenLabsBackend
from vaivox.infrastructure.stt.factory import create_stt_backend
from vaivox.infrastructure.stt.faster_whisper import FasterWhisperBackend
from vaivox.infrastructure.stt.openai import OpenAIBackend

ALL_BACKENDS = [FasterWhisperBackend, DeepgramBackend, ElevenLabsBackend, OpenAIBackend]
API_BACKENDS = [DeepgramBackend, ElevenLabsBackend, OpenAIBackend]

API_RESPONSES = [
    (OpenAIBackend, b'{"text": "Overlord bogey dope"}', "Overlord bogey dope"),
    (ElevenLabsBackend, b'{"text": "Texaco request rejoin"}', "Texaco request rejoin"),
    (
        DeepgramBackend,
        b'{"results": {"channels": [{"alternatives": [{"transcript": "Magic ready to copy"}]}]}}',
        "Magic ready to copy",
    ),
]


def make_config(tmp_path, settings):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "settings.cfg").write_text(settings, encoding="utf-8")
    (app_dir / "word_mappings.txt").write_text("", encoding="utf-8")
    (app_dir / "fuzzy_words.txt").write_text("", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return WhisperAttackConfiguration(str(app_dir), str(data_dir))


class FakeHTTPResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def fake_urlopen_factory(body):
    def fake_urlopen(_request, timeout=None):
        return FakeHTTPResponse(body)

    return fake_urlopen


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, _audio_path, **_kwargs):
        return self._segments, None


@pytest.mark.parametrize("backend_cls", ALL_BACKENDS)
def test_adapter_satisfies_speech_to_text_port(backend_cls, tmp_path):
    config = make_config(tmp_path, f"stt_backend={backend_cls.provider_name}\n")

    backend = backend_cls(config)

    assert isinstance(backend, SpeechToText)
    assert isinstance(backend.provider_name, str) and backend.provider_name


@pytest.mark.parametrize("backend_cls", ALL_BACKENDS)
def test_factory_builds_each_backend(backend_cls, tmp_path):
    config = make_config(tmp_path, f"stt_backend={backend_cls.provider_name}\n")

    backend = create_stt_backend(config)

    assert isinstance(backend, backend_cls)
    assert isinstance(backend, SpeechToText)


def test_factory_rejects_unknown_backend(tmp_path):
    config = make_config(tmp_path, "stt_backend=does-not-exist\n")

    with pytest.raises(SpeechToTextError):
        create_stt_backend(config)


@pytest.mark.parametrize("backend_cls", API_BACKENDS)
def test_api_adapter_load_without_key_raises_typed_error(backend_cls, tmp_path, monkeypatch):
    provider = backend_cls.provider_name
    monkeypatch.delenv("VAIVOX_CONTRACT_MISSING_KEY", raising=False)
    config = make_config(
        tmp_path,
        f"stt_backend={provider}\n{provider}_api_key_env=VAIVOX_CONTRACT_MISSING_KEY\n",
    )

    backend = backend_cls(config)

    with pytest.raises(SpeechToTextError):
        backend.load()


def test_faster_whisper_load_without_torch_raises_typed_error(tmp_path):
    if importlib.util.find_spec("torch") is not None:
        pytest.skip("torch is installed; the missing-dependency path is not exercised here")
    config = make_config(tmp_path, "stt_backend=faster_whisper\n")

    backend = FasterWhisperBackend(config)

    with pytest.raises(SpeechToTextError):
        backend.load()


def test_faster_whisper_transcribe_returns_normalized_transcription(tmp_path):
    config = make_config(tmp_path, "stt_backend=faster_whisper\n")
    backend = FasterWhisperBackend(config)
    backend.model = FakeWhisperModel([FakeSegment("hello "), FakeSegment("world")])

    result = backend.transcribe("ignored.wav")

    assert isinstance(result, Transcription)
    assert result.text == "hello world"


@pytest.mark.parametrize(("backend_cls", "response_bytes", "expected"), API_RESPONSES)
def test_api_adapter_transcribe_returns_normalized_transcription(
    backend_cls, response_bytes, expected, tmp_path, monkeypatch
):
    provider = backend_cls.provider_name
    monkeypatch.setenv("VAIVOX_CONTRACT_KEY", "test-key")
    config = make_config(
        tmp_path,
        f"stt_backend={provider}\n{provider}_api_key_env=VAIVOX_CONTRACT_KEY\n",
    )
    backend = backend_cls(config)
    backend.load()

    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFFdummy-audio")
    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen_factory(response_bytes))

    result = backend.transcribe(str(audio))

    assert isinstance(result, Transcription)
    assert result.text == expected
