VAIVOX
======

Quick start
-----------

1. Double-click "Set STT API Key.cmd" once and paste your provider API key.
2. Double-click "Install VAIVOX VoiceAttack Plugin.exe" to copy the plugin into your
   VoiceAttack 2 user Apps folder automatically and remove stale duplicate VAIVOX plugin
   copies from detected VoiceAttack install folders.
3. Import "VoiceAttack\VAIVOX - VA Profile.vap" in VoiceAttack.
4. In the imported profile, make sure the "Start VAIVOX Recording" and
   "Stop VAIVOX Recording" plugin actions point to the VAIVOX plugin.
5. Double-click "VAIVOX.exe".
6. Keep the "_internal" folder next to the exe.

VoiceAttack / VAICOM connects to the VAIVOX server on 127.0.0.1:65432.

VAICOM vocabulary enrichment
----------------------------

For best recognition, VAICOM must export its full keyword database before VAIVOX refreshes
the vocabulary.

1. In VAICOM Config, make sure the DCS variant points at the active Saved Games profile.
   For OpenBeta, the VAICOM log should show:

   SavedGamesFolder: C:\Users\<you>\Saved Games\DCS.openbeta

   If it still shows Saved Games\DCS, force Use custom path, select the DCS install root,
   and choose the OpenBeta variant.
2. In VAICOM Editor, click FINISH. This exports Export\keywords.txt and/or
   Export\keywords.html in the VAICOMPRO Apps folder and copies the full keyword list to
   the clipboard.
3. In VoiceAttack, edit the "VAICOM for DCS World" profile. Open the "AI Communications"
   command in the "Keyword Collections" category, clear "When I Say", paste the clipboard
   contents, then Apply/Done. If the label is not obvious, it is the large keyword command
   whose "When I Say" starts with "*AAA*; *Abort Inbound*; *Abort Refuel*; ...".
4. In VAIVOX, click "Refresh VAICOM vocabulary" or restart VAIVOX.

This enrichment is needed for module-specific phrases such as F-4E WSO/RIO commands.

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
