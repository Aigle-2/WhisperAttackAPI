VAIVOX
======

Quick start
-----------

1. Double-click "Set STT API Key.cmd" once and paste your provider API key.
2. Double-click "Install VAIVOX VoiceAttack Plugin.exe" to copy the plugin into your
   VoiceAttack 2 user Apps folder automatically.
3. Import "VoiceAttack\VAIVOX - VA Profile.vap" in VoiceAttack.
4. In the imported profile, make sure the "Start VAIVOX Recording" and
   "Stop VAIVOX Recording" plugin actions point to the VAIVOX plugin.
5. Double-click "VAIVOX.exe".
6. Keep the "_internal" folder next to the exe.

VoiceAttack / VAICOM connects to the VAIVOX server on 127.0.0.1:65432.

If the plugin installer cannot detect your VoiceAttack folder, it still installs to the
VoiceAttack 2 user plugin folder:

%APPDATA%\VoiceAttack2\Apps\VAIVOX

For a manual install, copy the contents of "VoiceAttack\Apps\VAIVOX" into that folder and
restart VoiceAttack.

VAIVOX can be installed alongside upstream WhisperAttack because it uses its own
VoiceAttack plugin GUID, Apps\VAIVOX folder, profile name, and %LOCALAPPDATA%\VAIVOX data
directory. Do not run both STT servers at the same time yet; the localhost ports are still
shared.

Configuration files
-------------------

- settings.cfg: backend and app settings.
- fuzzy_word.jsonl: default fuzzy-correction vocabulary.
- word_mapping.jsonl: default transcription replacement aliases.

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
