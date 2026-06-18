VAIVOX
======

Quick start
-----------

1. Double-click "Set STT API Key.cmd" once and paste your provider API key.
2. Double-click "VAIVOX.exe".
3. Keep the "_internal" folder next to the exe.

VoiceAttack / VAICOM connects to the VAIVOX server on 127.0.0.1:65432.

Configuration files
-------------------

- settings.cfg: backend and app settings.
- fuzzy_words.txt: DCS vocabulary used for fuzzy correction and STT keyterms.
- word_mappings.txt: transcription replacements used after STT.

Do not paste API keys into settings.cfg.

Logs
----

Logs are written to:

%LOCALAPPDATA%\VAIVOX\VAIVOX.log
