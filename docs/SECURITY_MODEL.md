# Security Model

VAIVOX is a local desktop companion for VoiceAttack, VAICOM, and DCS. It is not designed
as a network service.

## Local Sockets

- The inbound control socket binds to `127.0.0.1:65432` by default.
- The VoiceAttack plugin listener is expected on `127.0.0.1:65433`.
- Non-local control binds are refused at runtime.
- A non-local `voiceattack_host` logs a warning because commands would leave the local
  machine.

## Introspection API

The HTTP introspection API is off by default. When enabled, it is restricted to localhost
binds and can require a bearer token with `api_token`.

Mutating actions are separately gated by `api_actions_enabled=false` by default. POST
bodies are capped by `api_max_post_bytes`; oversized requests return `413 Payload Too
Large`.

## Secrets

Provider keys should live in user environment variables, not in `settings.cfg`. VAIVOX
redacts config keys containing `api_key`, `token`, `secret`, or `password` before writing
configuration to the UI, logs, or introspection responses.

## Telemetry

Telemetry is local-only and enabled by default. It writes reconciliation records,
including transcribed utterance text, to `%LOCALAPPDATA%\VAIVOX\telemetry.jsonl`.

Set `telemetry_enabled=false` in `settings.cfg` to disable telemetry.
