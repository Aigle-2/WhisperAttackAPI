# VAIVOX - STT Backends for VoiceAttack

This repository provides a single-server approach for using modern speech-to-text (STT) backends with VoiceAttack, replacing Windows Speech Recognition with accurate push-to-talk transcription.

This fork keeps the WhisperAttack workflow but adds a provider-agnostic STT backend layer. The default backend is ElevenLabs Scribe v2 for API-based transcription that does not consume the GPU DCS needs. The original local `faster_whisper` workflow remains available as a configurable fallback.

This is a fork for further integration of **KneeboardWhisper** by the amazing creator [@BojoteX](https://github.com/BojoteX). A special thank you goes to [@hradec](https://github.com/hradec), whose original script used Google Voice Recognition, [@SeaTechNerd83](https://github.com/SeaTechNerd83) for helping combine the two approaches and creating a VA plugin and finally [@sleighzy](https://github.com/sleighzy) for VAICOM implementation and the lengthy list of bug fixes and enchancements that would fill this page

In short, SeaTechNerd83 and I combined the two scripts to run voice commands through Whisper using BojoteX's code and then pushed it into VoiceAttack using hradec's code. To speed this up, I unified the codebase into one file and made it run a server to send commands to VoiceAttack. VAIVOX will run on any Nvidia GPU with 6GB or more of VRAM and will run along with DCS (performance tuning may be required for lower VRAM cards) although absolute minimum spec GPU has not yet been confirmed, RTX 2060 6gb and GTX 1070 8gb have been confirmed working stutter free alongside DCS in VR.

> **VAIVOX** is an independent companion project for the DCS voice ecosystem. It is **not
> affiliated with, or endorsed by, VAICOM Community** — it simply works alongside it.
> VAICOM(PRO)-Community is the community-maintained, open-source successor to VAICOM PRO
> ([VAICOMPRO-Community on GitHub](https://github.com/Hollywood-VAICOM/VAICOMPRO-Community)).
> VAIVOX is a divergence of [WhisperAttack](https://github.com/BojoteX/KneeboardWhisper) /
> KneeboardWhisper; see the credits above.

---

## Features

- **Provider-agnostic STT backends**:
  - Records mic audio on demand (via socket commands).
  - Transcribes the `.wav` file using the configured backend.
  - Sends recognized text into VoiceAttack.
  - Pushes transcribed text to clipboard - (perfect for voice to text DCS Chat...)
  - Supports the original local `faster_whisper` backend.
  - Supports ElevenLabs Scribe v2 via API.
  - Supports OpenAI `gpt-4o-transcribe` via API.
  - Supports Deepgram Nova-3 via API.

- **VoiceAttack Command Plugin**
  - Sends "start", "stop", or "shutdown" commands to the server directly through VoiceAttack.

- **Advantages:**
  - API-backed STT avoids using GPU resources needed by DCS.
  - Local Whisper can still be used offline when preferred.
  - Push-to-Talk style workflow with VoiceAttack press & release.
  - STT keyterms can bias recognition toward DCS, VAICOM, ATC, callsigns, and airfields.

---

## VAICOM integration

Instructions for integrating with VAICOM can be located in the [VAICOM INTEGRATION](./VAICOM%20PRO/VAICOM_INTEGRATION.md) documentation.

---

## Requirements

- **VoiceAttack**
  - [voiceattack.com](https://voiceattack.com)
  - Plugins Enabled

- **GPU (Optional, but Recommended)**
  - Only required when using the `faster_whisper` backend.
  - API-backed providers do not use local GPU resources.

- **API key (API backends)**
  - Create an API key for the provider configured in `settings.cfg`.
  - Set it with `Set STT API Key.cmd` from the release folder.
  - Do not put API keys in `settings.cfg` or commit them to the repository.

---

## Installation

These instructions are for normal users. You do not need Python, Git, Visual Studio, CUDA, or any developer tooling when using the release ZIP.

1. Download the latest `VAIVOX` release ZIP from GitHub Releases.
1. Extract the ZIP anywhere on your computer, for example:

```console
C:\Program Files\VAIVOX
```

or:

```console
C:\Users\yourname\Desktop\VAIVOX
```

1. Open the extracted folder.
1. Double-click `Set STT API Key.cmd` once and paste your provider API key.
1. Double-click `VAIVOX.exe`.
1. Create a shortcut to `VAIVOX.exe` if desired.

Keep the folder structure intact. Do not move only the `.exe` file elsewhere; it must stay beside `_internal`, `settings.cfg`, `fuzzy_words.txt`, `word_mappings.txt`, and the icon files.

The release folder is expected to look like this:

```console
VAIVOX v1.2.2-api.1\
  _internal\
  VAIVOX.exe
  settings.cfg
  fuzzy_words.txt
  word_mappings.txt
  vaivox_icon.png
  add_icon.png
  Set STT API Key.cmd
  Set ElevenLabs API Key.cmd
  README_FIRST.txt
```

The VoiceAttack plugin connects to the VAIVOX server on `127.0.0.1:65432`. Because VAIVOX
ships a freshly-GUID'd plugin (separate from upstream WhisperAttack), re-point each
VoiceAttack command's plugin function to the **VAIVOX** plugin — see
[plugin/VaivoxVAPlugin/README.md](plugin/VaivoxVAPlugin/README.md).

---

## Configuration

The default configuration files are stored beside the VAIVOX application. Custom configuration can be kept in
files of the same name in the `C:\Users\username\AppData\Local\VAIVOX` directory. These custom files can be created
if they do not exist and can be used to override (or add to for word mappings) the default configuration.

Keeping custom configuration at that location means it will not be overwritten when installing later versions of VAIVOX.

See below for the list of configuration files.

### settings.cfg

The `settings.cfg` file contains configuration for VAIVOX.

The default values should cover most cases but can be changed:

- `stt_backend` - The speech-to-text backend to use, `elevenlabs` by default in this fork.
  - Supported values: `elevenlabs`, `openai`, `deepgram`, `faster_whisper`
- `stt_language` - Language hint for transcription, `en` by default for VAICOM English commands.
- `stt_timeout_seconds` - API request timeout in seconds.
- `stt_keyterm_sources` - Comma-separated sources used to build provider keyterms without duplicating vocabulary in `settings.cfg`.
  - Supported values: `custom`, `phonetic_alphabet`, `fuzzy_words`, `word_mapping_replacements`, `word_mapping_aliases`, `dcs_default`, `vaicom`
- `stt_keyterms_extra` - Optional comma-separated extra provider keyterms. Prefer `fuzzy_words.txt` for domain vocabulary.
- `elevenlabs_api_key_env` - Environment variable containing the ElevenLabs API key. Defaults to `ELEVENLABS_API_KEY`.
- `elevenlabs_model` - ElevenLabs model ID, `scribe_v2` by default.
- `elevenlabs_no_verbatim` - Removes filler words and false starts when supported. Defaults to `true`.
- `elevenlabs_tag_audio_events` - Enables or disables audio event tags. Defaults to `false`.
- `elevenlabs_timestamps_granularity` - Timestamp granularity. Defaults to `none` because VoiceAttack only needs text.
- `elevenlabs_max_keyterms` - Maximum generated keyterms to send to ElevenLabs. Defaults to `900`.
- `elevenlabs_max_keyterm_chars` - Maximum characters per ElevenLabs keyterm. Defaults to `50`.
- `openai_api_key_env` - Environment variable containing the OpenAI API key. Defaults to `OPENAI_API_KEY`.
- `openai_model` - OpenAI transcription model ID, `gpt-4o-transcribe` by default.
- `openai_include_keyterms_in_prompt` - Adds generated DCS/VAICOM keyterms to the OpenAI transcription prompt.
- `openai_max_prompt_keyterms` - Maximum generated keyterms to include in the OpenAI prompt.
- `openai_prompt_keyterm_char_budget` - Maximum generated keyterm text length to add to the OpenAI prompt.
- `deepgram_api_key_env` - Environment variable containing the Deepgram API key. Defaults to `DEEPGRAM_API_KEY`.
- `deepgram_model` - Deepgram model ID, `nova-3` by default.
- `deepgram_smart_format` - Enables Deepgram smart formatting. Defaults to `true`.
- `deepgram_detect_language` - Lets Deepgram detect the spoken language instead of sending `stt_language`.
- `deepgram_max_keyterms` - Maximum generated keyterms to send as Deepgram `keyterm` parameters.
- `whisper_model` - The Whisper model to use, `small.en` by default. See the table at the bottom of the README file for options.
  - A smaller size can be specified for reducing the amount of VRAM used, e.g. `base.en` or `tiny.en`
- `whisper_device` - Which device to run the Whisper transcription process on, `GPU` (default) or `CPU`
- `theme` - To display the VAIVOX UI in light or dark mode. Valid values: 
  - `default` - this will use the current theme you have set for Windows
  - `dark` - dark mode
  - `light` - light mode

### API key setup

For release users, use the helper included beside the exe:

```console
Set STT API Key.cmd
```

This stores the selected provider key in your Windows user environment. The key is not written to `settings.cfg`.

PowerShell alternative:

```console
setx ELEVENLABS_API_KEY "your-api-key"
setx OPENAI_API_KEY "your-api-key"
setx DEEPGRAM_API_KEY "your-api-key"
```

Restart VAIVOX after setting the environment variable.

### VAICOM keyterms

VAIVOX does **not** ship VAICOM-derived vocabulary — redistributing data derived from a
VAICOM install is a licensing grey zone (ADR-0005). Out of the box VAIVOX runs on a
generic, non-VAICOM seed (the phonetic alphabet plus widely-documented DCS callsigns and
ATC vocabulary), so recognition is biased toward DCS terms immediately.

To bias recognition toward *your* actual VAICOM install, generate the vocabulary locally.
The generator **auto-discovers** the VAICOM install (it checks `VAICOMPRO_DIR` and the
common VoiceAttack `Apps` locations under Program Files / Steam) and writes two files into
`%LOCALAPPDATA%\VAIVOX`:

- `vaicom_keyterms.txt` — STT keyterms (the `vaicom` keyterm source loads it; override the
  path with `VAIVOX_VAICOM_KEYTERMS`).
- `phrase_index.txt` — the valid command phrases the Axis B phrase snapper matches against
  (override with `VAIVOX_PHRASE_INDEX`).

```console
python tools\generate_vaicom_keyterms.py
```

Pass `--vaicom-root` / `--saved-games` if auto-discovery misses a non-standard install,
and `--data-dir` to write elsewhere.

The generated list is post-processed into unique words: composed phrases, numeric tokens,
low-value UI words, and code-only terms such as ICAO identifiers are removed. Technical
acronyms such as `IFF`, `TV`, and `TACAN` are placed first, high-value command words such
as `boresight`, `clearance`, and `wheelchocks` follow, then callsigns, common DCS terms,
and selected proper names. Use `--max-terms` to raise or lower the shortlist size.

Spelled aviation codes are normalized after transcription, so the keyterm list does not
need to include every code. For example, `U L M B`, `U-L-M-B`, or `E.S.N.J` are compacted
to `ULMB` and `ESNJ` before text is sent to VoiceAttack.

> Background generation on first run + an in-app "Refresh VAICOM vocabulary" control are
> still planned (ADR-0005); for now run the generator above once (and again after you
> change your VAICOM setup).

### Optional STT providers

ElevenLabs remains the default because it has worked well for DCS/VAICOM push-to-talk with French-accented English. Users can switch providers by editing `settings.cfg`:

```console
stt_backend=openai
```

OpenAI uses the official transcription endpoint with `gpt-4o-transcribe` by default. VAIVOX sends the DCS/VAICOM prompt and a budgeted set of generated keyterms as transcription context. See the official [OpenAI Speech-to-Text guide](https://developers.openai.com/api/docs/guides/speech-to-text) and [transcription API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create/).

```console
stt_backend=deepgram
```

Deepgram uses prerecorded transcription with `nova-3` by default. VAIVOX sends a budgeted set of generated DCS/VAICOM keyterms as Deepgram `keyterm` query parameters. See the official [Deepgram prerecorded audio guide](https://developers.deepgram.com/docs/pre-recorded-audio), [Nova-3 model overview](https://developers.deepgram.com/docs/models-languages-overview), and [Keyterm Prompting docs](https://developers.deepgram.com/docs/keyterm).

### ElevenLabs cost estimate

Pricing can change, so check the official [ElevenLabs API pricing page](https://elevenlabs.io/pricing/api) before publishing guidance to users. The [ElevenLabs Speech-to-Text docs](https://elevenlabs.io/docs/overview/capabilities/speech-to-text) describe Scribe v2, language support, and keyterm prompting. The estimate below was checked on 2026-06-18.

VAIVOX currently uses `scribe_v2` in batch Speech-to-Text mode, not `Scribe v2 Realtime`. The default configuration sends DCS/VAICOM keyterms, so the estimate includes keyterm prompting.

Assumptions:

- Scribe v1/v2 Speech-to-Text: `$0.22` per transcribed audio hour.
- Keyterm prompting: `+$0.05` per transcribed audio hour.
- Entity detection is not used.
- Realtime transcription is not used.
- Estimated total: `$0.27` per transcribed audio hour, before taxes.

With `$5`:

```console
$5 / $0.27 = 18.5 hours of transcribed audio
```

This is not the same as 18.5 hours of gameplay. VAIVOX only sends audio while push-to-talk is recording.

| Usage style | Transcribed audio per gameplay hour | Estimated cost per gameplay hour | $5 covers about |
| --- | ---: | ---: | ---: |
| Light radio use | 30 seconds | $0.00225 | 2200 gameplay hours |
| Normal VAICOM use | 2 minutes | $0.009 | 555 gameplay hours |
| Intensive radio use | 5 minutes | $0.0225 | 222 gameplay hours |
| Very chatty / dictation | 15 minutes | $0.0675 | 74 gameplay hours |
| Push-to-talk nearly always held | 60 minutes | $0.27 | 18.5 gameplay hours |

A typical 3-second command costs roughly:

```console
$0.27 / 3600 * 3 = $0.000225
```

So `$5` covers about `22,000` short 3-second commands under the straight audio-duration estimate.

Important caveat: ElevenLabs documents Speech-to-Text as billed per audio minute, but the public pricing page does not clearly state whether many very short API requests are rounded up individually. If each short push-to-talk clip were rounded up to one full minute, `$5` would cover about `1,111` commands instead. The safest validation is to send a small number of test commands, then check usage in the ElevenLabs developer dashboard.

### Building the executable (maintainers only)

Normal users should download the release ZIP and should not run this step. The recommended maintainer build is the API-only executable. It avoids bundling Torch and faster-whisper, so the package is smaller and DCS keeps priority on the GPU.

Double-click:

```console
build_api_only.cmd
```

The executable is created at:

```console
dist\release\VAIVOX v1.2.2-api.1\VAIVOX.exe
```

The distributable ZIP is created beside it:

```console
dist\release\VAIVOX v1.2.2-api.1.zip
```

Any intermediate PyInstaller output is kept under `build`; only `dist\release` is meant to be published.

The release folder follows the same flat layout: the exe, `_internal`, `settings.cfg`, `fuzzy_words.txt`, `word_mappings.txt`, icons, and a small API-key helper are all at the top level.

To build the larger offline-capable executable that includes the local `faster_whisper` backend, double-click:

```console
build_full.cmd
```

### Local Whisper setup

To run fully offline, update `settings.cfg`:

```console
stt_backend=faster_whisper
whisper_model=small.en
```

This requires the full executable built with `build_full.cmd` or a Python environment set up with `uv sync --extra full`.

### word_mappings.txt

The `word_mappings.txt` file contains keys and values that can be used to replace a spoken word with another word. For example, if the transcription often outputs "Inter" when you are saying "Enter" then this can be added as a word placement.

The word replacement configuration also supports specifying multiple words to be replaced with a single word, these are separated by a semicolon `;`. In the example below saying either "gulf" or "gold" would be replaced with "Golf".

```
gulf;gold=Golf
inter=Inter
```

VAIVOX needs to be restarted after making changes to this file. New word mappings can be added via the configuration screen and do not require a restart. When adding new word mappings they will be created in your custom configuration file, `C:\Users\username\AppData\Local\VAIVOX\word_mappings.txt`

---

## Running the Whisper Server

Double click the `VAIVOX.exe` file or shortcut. This will open an application window and start the server.

The application window will display startup logging information, including the effective STT keyterm context, the raw text transcribed from the speech, and the final cleaned up command text that was sent to VoiceAttack or DCS. The window can be closed, and then shown again from the menu in the VAIVOX icon in the Windows system tray. VAIVOX will continue running even when the window is closed.

VAIVOX will have completed loading once the "Server started and listening" message is displayed.

```
Loaded STT keyterm context:
provider: elevenlabs
sources: custom=0, phonetic_alphabet=26, fuzzy_words=..., word_mapping_replacements=..., dcs_default=24, vaicom=850
available: ... unique terms
effective: ... terms sent to elevenlabs
Loading STT backend (elevenlabs) ...
Server started and listening on 127.0.0.1:65432...
```

![whisperattack_voiceattack](./screenshots/WhisperAttack%20UI%20and%20VoiceAttack.png)

A VAIVOX icon will be placed in your Windows system tray. Right-clicking this will give options to show the VAIVOX window, or to exit the application.

![whisperattack_systemtrayicon](./screenshots/WhisperAttack%20system%20tray.png)

Closing VoiceAttack will also stop and close VAIVOX.

**NOTE:** There may be a slow startup time for the Whisper Model to download. This process only needs to take place once (unless you change the Whisper Model to be used)

The Whisper server will output logs to the `C:\Users\username\AppData\Local\VAIVOX\VAIVOX.log` file.

---

## Configuring VoiceAttack

Pre-configured Voice Attack Profile is added to the release for your convenience. It is recommended to read through the steps below to understand how whisper injections actually work!

### 1. Disable all speech recognition within VoiceAttack

<img width="825" alt="Disable_speech_recognition" src="https://github.com/user-attachments/assets/1bf08530-4a05-4b19-92a5-560879b50936" />

<img width="840" alt="VoiceAttack_startup" src="https://github.com/user-attachments/assets/fc0bfd3c-d0aa-4501-95ce-a31fa9c78790" />

### 2. Enable Plugin support in VoiceAttack

Go to **Options → General → Enable Plugin Support**.

![EnablePluginsVA](https://github.com/user-attachments/assets/8bb6faf2-4aa4-416b-99cd-6b9b2a6c0097)

### 3. Place Plugin in VoiceAttack Apps folder

Build the VAIVOX plugin (see [plugin/VaivoxVAPlugin/README.md](plugin/VaivoxVAPlugin/README.md)), then locate the `VAIVOX` plugin folder and copy the entire folder

![image](https://github.com/user-attachments/assets/dcd75f43-b957-4551-86bf-650468586834)

Locate the VoiceAttack Apps Folder

![image](https://github.com/user-attachments/assets/413de21d-e7a8-4086-ad9f-c97354716ab3)

Paste the entire `VAIVOX` folder into the Apps folder

![image](https://github.com/user-attachments/assets/fd856417-34b7-4f39-b3a9-bf4ea0e79871)

If the plugin is enabled and active and everything is set up correctly, VoiceAttack should give these messages on startup:

![image](https://github.com/user-attachments/assets/287e0a3c-7891-40a1-96bf-842f26dccd77)


### 4. Create Recording commands

In VoiceAttack, go to **Edit Profile**.

#### New Command for "Start Whisper Recording":

- **When this command executes:**
  - Go to **Other → Advancced → Execute an External Plugin Function**.
  - **Plugin**: Point it to the 'VAIVOX' plugin
  - **Plugin Context:**

```
Start Whisper Recording
```

Assign a joystick or key press to this command (e.g., "Joystick Button 14 (pressed)").

![Whisperattackreadme](https://github.com/user-attachments/assets/ee96bc06-8fe6-45b0-9999-076eb0e0cc00)

#### Another Command for "Stop Whisper Recording":

Same steps, except the **Parameters** is:

```
Stop Whisper Recording
```

Assign the same joystick button but check **"Shortcut is invoked only when released."**

![Whisperattackreadme1](https://github.com/user-attachments/assets/9c84d4f8-00c0-4525-8cda-0c0ddda24298)

---
## Adding new word mappings

Word mappings can be added to VAIVOX so that when these words are found within transcribed sentences they will be replaced with the replacement word you provide. This can aid with replacing words that are consistently transcribed incorrectly into the word you actually want.

Click the Add word mapping button to open this configuration screen. Multiple aliases can be entered, separated by semicolons, for a single replacement.

![whisperattack_addwordmapping](./screenshots/WhisperAttack%20add%20new%20word%20mapping.png)

---
## Clipboard & DCS Kneeboard Integration - Optional

This script preserves BojoteX original vision for the code and copies the commands into clipboard for use with the Kneeboard.
The original repo can be found here: [https://github.com/BojoteX/KneeboardWhisper](https://github.com/BojoteX/KneeboardWhisper?tab=readme-ov-file#troubleshooting)

Do the following to enable DCS Kneeboard to transcribe what you say:
Once completed, you must say "Note" followed by what you would like to transcribe to kneeboard/clipboard

![assignments](https://github.com/user-attachments/assets/6528e6a7-4114-4fdb-a1bc-1ed68bd6a1f8)

![kneeboardwhisper](https://github.com/user-attachments/assets/71874a7d-5c09-4b8c-b174-8693653ac82f)

---

## Troubleshooting

### Library cublas64_12.dll is not found

If the below below is displayed in the logs then ensure that CUDA 12 is available, e.g. by installing the [CUDA Toolkit 12](https://developer.nvidia.com/cuda-downloads)

```console
ERROR - Failed to transcribe audio: Library cublas64_12.dll is not found or cannot be loaded
```

### ValueError: Requested int8_float16 compute type ###

For some GPUs which do not support certain compute types, i.e. do not have tensor cores, the below message will be output to the logs:

```
WARNING - GPU does not have tensor cores, major=6, minor=1
```

VAIVOX can detect this and will fallback on supported values for cuda cores.

If however the below error message is displayed then the `settings.cfg` file can be updated.

```console
ValueError: Requested int8_float16 compute type, but the target device or backend do not support efficient int8_float16 computation.
```

The `settings.cfg` file can be updated to add the below entry:

```console
whisper_core_type=standard
```

---

## Performance (AI Model)

If DCS is GPU constrained, use an API backend such as ElevenLabs so transcription does not consume VRAM. This is the default in VAIVOX:

```console
stt_backend=elevenlabs
elevenlabs_model=scribe_v2
```

If you use the local `faster_whisper` backend and VAIVOX is causing significant studders, it is likely that the current model is overloading your VRAM. In that case, reduce the local Whisper model size:

```console
stt_backend=faster_whisper
whisper_model=base.en
```

- Using smaller models will reduce VRAM and compute costs. See below for a full speed breakdown
- First activation with a new AI model will prompt the model to be downloaded which may take an extended amount of time depending on internet speed.

---

## Available models and languages

There are six model sizes, four with English-only versions, offering speed and accuracy tradeoffs.
Below are the names of the available models and their approximate memory requirements and inference speed relative to the large model.
The relative speeds below are measured by transcribing English speech on a A100, and the real-world speed may vary significantly depending on many factors including the language, the speaking speed, and the available hardware.

|  Size  | Parameters | English-only model | Multilingual model | Required VRAM | Relative speed |
|:------:|:----------:|:------------------:|:------------------:|:-------------:|:--------------:|
|  tiny  |    39 M    |     `tiny.en`      |       `tiny`       |     ~1 GB     |      ~10x      |
|  base  |    74 M    |     `base.en`      |       `base`       |     ~1 GB     |      ~7x       |
| small  |   244 M    |     `small.en`     |      `small`       |     ~2 GB     |      ~4x       |
| medium |   769 M    |    `medium.en`     |      `medium`      |     ~5 GB     |      ~2x       |
| large  |   1550 M   |        N/A         |      `large`       |    ~10 GB     |       1x       |
| turbo  |   809 M    |        N/A         |      `turbo`       |     ~6 GB     |      ~8x       |

The `.en` models for English-only applications tend to perform better, especially for the `tiny.en` and `base.en` models. We observed that the difference becomes less significant for the `small.en` and `medium.en` models.
Additionally, the `turbo` model is an optimized version of `large-v3` that offers faster transcription speed with a minimal degradation in accuracy.

Whisper's performance varies widely depending on the language. The figure below shows a performance breakdown of `large-v3` and `large-v2` models by language, using WERs (word error rates) or CER (character error rates, shown in *Italic*) evaluated on the Common Voice 15 and Fleurs datasets. Additional WER/CER metrics corresponding to the other models and datasets can be found in Appendix D.1, D.2, and D.4 of [the paper](https://arxiv.org/abs/2212.04356), as well as the BLEU (Bilingual Evaluation Understudy) scores for translation in Appendix D.3.

Enjoy your local (offline) speech recognition with OpenAI Whisper + VoiceAttack! If you run into issues, open an issue or check the logs for clues.
