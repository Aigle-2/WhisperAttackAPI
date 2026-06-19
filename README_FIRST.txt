VAIVOX
======

Quick start
-----------

1. Double-click "Set STT API Key.cmd" once and paste your provider API key.
2. Copy "VoiceAttack\Apps\VAIVOX\VaivoxVAPlugin.dll" into your VoiceAttack Apps folder,
   keeping the VAIVOX folder name.
3. Import "VoiceAttack\VAIVOX - VA Profile.vap" in VoiceAttack.
4. In the imported profile, make sure the "Start VAIVOX Recording" and
   "Stop VAIVOX Recording" plugin actions point to the VAIVOX plugin.
5. Double-click "VAIVOX.exe".
6. Keep the "_internal" folder next to the exe.

VoiceAttack / VAICOM connects to the VAIVOX server on 127.0.0.1:65432.

Configuration files
-------------------

- settings.cfg: backend and app settings.
- fuzzy_words.txt: DCS vocabulary used for fuzzy correction and STT keyterms.
- word_mappings.txt: transcription replacements used after STT.

Do not paste API keys into settings.cfg. Use "Set STT API Key.cmd" so keys are stored in
your Windows user environment instead.

Telemetry and logs
------------------

Logs are written to:

%LOCALAPPDATA%\VAIVOX\VAIVOX.log

Telemetry is enabled by default and is local only. It writes reconciliation events,
including transcribed utterance text, to:

%LOCALAPPDATA%\VAIVOX\telemetry.jsonl

Set telemetry_enabled=false in settings.cfg to disable telemetry.

Security notes
--------------

VAIVOX sockets and the optional introspection API are designed for localhost only. Keep
control_host, voiceattack_host, and api_host on 127.0.0.1 unless you are deliberately
debugging a local-only setup.
