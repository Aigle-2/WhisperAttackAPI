WhisperAttackAPI
================

Quick start
-----------

1. Double-click "Set STT API Key.cmd" once and paste your provider API key.
2. Double-click "WhisperAttackAPI.exe".
3. Keep the "_internal" folder next to the exe.

VoiceAttack / VAICOM setup stays the same as WhisperAttack when it connects to
127.0.0.1:65432.

Configuration files
-------------------

- settings.cfg: backend and app settings.
- fuzzy_words.txt: DCS vocabulary used for fuzzy correction and STT keyterms.
- word_mappings.txt: transcription replacements used after STT.

Do not paste API keys into settings.cfg.

Logs
----

Logs are written to:

%LOCALAPPDATA%\WhisperAttack\WhisperAttack.log
