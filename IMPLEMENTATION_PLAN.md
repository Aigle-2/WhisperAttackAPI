# WhisperAttackAPI Implementation Plan

## Goals

- Keep the existing WhisperAttack and VoiceAttack workflow intact.
- Move speech-to-text behind a provider-agnostic interface.
- Make all backend behavior configurable from `settings.cfg`.
- Avoid committing personal data, API keys, local audio, logs, or caches.
- Prefer API-backed STT first so DCS keeps priority on the local GPU.
- Preserve the original local `faster_whisper` path for offline use.
- Ship an API-only executable as the recommended deployment, with a full executable as an optional offline build.

## Current Implementation

- `stt_backends/base.py` defines the normalized STT contract.
- `stt_backends/factory.py` selects the backend from `stt_backend`.
- `stt_backends/elevenlabs_backend.py` implements ElevenLabs Scribe v2 over HTTPS.
- `stt_backends/faster_whisper_backend.py` keeps the previous local Whisper behavior behind the same contract.
- `whisper_server.py` now loads one STT backend and keeps the existing cleanup, fuzzy matching, clipboard, VoiceAttack, and kneeboard flow.
- `configuration.py` exposes generic, provider-specific, and safe redacted settings accessors.
- `settings.cfg` documents the default ElevenLabs backend, source-driven keyterms, and the local Whisper fallback.
- `build_exe.ps1` creates API-only or full PyInstaller executables.

## Settings Contract

- Generic STT settings use `stt_*`.
- Provider settings use `{provider}_*`.
- Provider settings override generic settings where both exist.
- Provider keyterms are generated from configured sources such as `fuzzy_words.txt`, `word_mappings.txt`, the phonetic alphabet, and DCS defaults.
- Secrets are referenced through environment variable names such as `elevenlabs_api_key_env`.
- Direct secret values should never be stored in `settings.cfg`.

## Provider Adapter Checklist

1. Add a backend class implementing `SpeechToTextBackend`.
2. Read all options from `WhisperAttackConfiguration`.
3. Normalize output to `SpeechToTextResult`.
4. Raise `SpeechToTextBackendError` for provider failures.
5. Register the backend in `stt_backends/factory.py`.
6. Add focused unit tests for config parsing, request shape, and response parsing.
7. Document the settings in `README.md` and `settings.cfg`.

## Recommended Next Providers

- OpenAI `gpt-4o-transcribe`: strong candidate for accented English and prompt-based domain context.
- AssemblyAI Universal-3 Pro: strong candidate when natural-language prompting and large keyterm lists matter.
- Deepgram or Soniox: candidates if low-latency streaming becomes more important than push-to-talk file transcription.

## Review Notes

- The current fork uses synchronous file transcription because VoiceAttack push-to-talk already records a complete `.wav` command.
- ElevenLabs keyterms are generated from existing vocabulary sources for DCS, VAICOM, callsigns, and radio vocabulary biasing.
- ElevenLabs does not support a natural-language transcription prompt in the same way OpenAI does; `stt_prompt` is therefore reserved for providers that support it.
- The API-only build intentionally cannot run `stt_backend=faster_whisper`; use `build_full.cmd` for offline Whisper.
- A real provider integration test should be run locally with a short non-sensitive audio file and an API key from the environment.
