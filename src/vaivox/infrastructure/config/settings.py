"""Settings reader: load ``settings.cfg`` from disk.

This is the infrastructure adapter behind the :class:`~vaivox.application.ports.ConfigProvider`
port. Default values ship with the app; user overrides live in the per-user
``%LOCALAPPDATA%`` VAIVOX directory and are merged on top.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from ipaddress import ip_address

from vaivox.infrastructure.config.identity import VAIVOX

_DEFAULT_THEME = "default"
_DEFAULT_API_MAX_POST_BYTES = 16 * 1024
_REDACTED = "<redacted>"
_SENSITIVE_KEY_PARTS = ("api_key", "secret", "token", "password")
_LOCALHOST_NAMES = {"localhost"}


class ConfigurationError(Exception):
    """Raised when configuration files cannot be read or written."""


def _redact_configuration(config: Mapping[str, str]) -> dict[str, str]:
    """Return ``config`` with secret-looking values redacted for logs/API output."""
    safe_config: dict[str, str] = {}
    for key, value in config.items():
        lower_key = key.lower()
        if lower_key.endswith("_env"):
            safe_config[key] = value
        elif any(part in lower_key for part in _SENSITIVE_KEY_PARTS):
            safe_config[key] = _REDACTED if value else ""
        else:
            safe_config[key] = value
    return safe_config


def _is_loopback_host(host: str) -> bool:
    """Return whether ``host`` names a local loopback address."""
    normalized = host.strip().lower()
    if normalized in _LOCALHOST_NAMES:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


class VaivoxConfiguration:
    """Read and write the application configuration.

    Default configuration is loaded from the application directory; custom
    configuration is loaded from the per-user ``%LOCALAPPDATA%`` VAIVOX directory and
    merged on top of the defaults.
    """

    def __init__(self, app_location: str, app_data_location: str) -> None:
        """Load and merge the default and custom configuration.

        Args:
            app_location: Directory holding the shipped default configuration.
            app_data_location: Directory holding the user's custom overrides.
        """
        self._app_location = app_location
        self._app_data_location = app_data_location

        default_config = self.load_configuration(app_location)
        custom_config = self.load_configuration(app_data_location, False)
        self.config = default_config | custom_config

    def load_configuration(self, location: str, default: bool = True) -> dict[str, str]:
        """Load configuration settings from ``settings.cfg``.

        Args:
            location: Directory to read ``settings.cfg`` from.
            default: Whether a missing file is a fatal error (defaults are required).

        Returns:
            The parsed ``key=value`` settings.

        Raises:
            ConfigurationError: If the file cannot be read, or is missing when required.
        """
        logging.info("Loading %s configuration...", "default" if default else "custom")
        config: dict[str, str] = {}
        settings_file = os.path.join(location, "settings.cfg")
        if os.path.isfile(settings_file):
            try:
                with open(settings_file, encoding="utf-8") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split("=", maxsplit=1)
                        if len(parts) == 2:
                            source, target = parts
                            config[source.strip()] = target.strip()
            except Exception as error:
                logging.error(
                    "Failed to load configuration settings from '%s': %s", settings_file, error
                )
                raise ConfigurationError("Failed to load configuration settings") from error
        elif default:
            logging.error("File not found: '%s'", settings_file)
            raise ConfigurationError("The configuration settings.cfg file could not be found")

        logging.info("Loaded configuration: %s", _redact_configuration(config))
        return config

    @property
    def app_location(self) -> str:
        """Return the application directory holding bundled defaults and assets."""
        return self._app_location

    @property
    def app_data_location(self) -> str:
        """Return the per-user data directory (config, logs, telemetry, generated files)."""
        return self._app_data_location

    def get_configuration(self) -> dict[str, str]:
        """Return the full merged configuration."""
        return self.config

    def get_safe_configuration(self) -> dict[str, str]:
        """Return configuration values with sensitive local settings redacted."""
        return _redact_configuration(self.config)

    def get_setting(self, key: str, default: str = "") -> str:
        """Return a raw string configuration setting."""
        return self.config.get(key, default)

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        """Return a boolean configuration setting."""
        value = self.config.get(key)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")

    def get_int_setting(
        self,
        key: str,
        default: int,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        """Return an integer configuration setting, bounded and fallback-safe."""
        value = self.config.get(key)
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            logging.warning(
                "Invalid integer value for '%s': %s. Using default %s.", key, value, default
            )
            return default
        if min_value is not None and parsed < min_value:
            logging.warning(
                "Integer value for '%s' below minimum (%s < %s). Using default %s.",
                key,
                parsed,
                min_value,
                default,
            )
            return default
        if max_value is not None and parsed > max_value:
            logging.warning(
                "Integer value for '%s' above maximum (%s > %s). Using default %s.",
                key,
                parsed,
                max_value,
                default,
            )
            return default
        return parsed

    def get_float_setting(self, key: str, default: float) -> float:
        """Return a float configuration setting, falling back to ``default``."""
        value = self.config.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            logging.warning(
                "Invalid float value for '%s': %s. Using default %s.", key, value, default
            )
            return default

    def get_provider_setting(self, provider: str, key: str, default: str = "") -> str:
        """Return a provider-specific setting, falling back to a generic ``stt_*`` one."""
        return self.config.get(f"{provider}_{key}", self.config.get(f"stt_{key}", default))

    def get_provider_bool(self, provider: str, key: str, default: bool = False) -> bool:
        """Return a provider-specific boolean setting."""
        provider_key = f"{provider}_{key}"
        if provider_key in self.config:
            return self.get_bool_setting(provider_key, default)
        return self.get_bool_setting(f"stt_{key}", default)

    def get_provider_int(self, provider: str, key: str, default: int) -> int:
        """Return a provider-specific integer setting."""
        provider_key = f"{provider}_{key}"
        if provider_key in self.config:
            return self.get_int_setting(provider_key, default)
        return self.get_int_setting(f"stt_{key}", default)

    def get_stt_backend(self) -> str:
        """Return the speech-to-text backend provider to use."""
        return self.config.get("stt_backend", "faster_whisper").strip().lower()

    def get_stt_language(self) -> str:
        """Return the language hint used for transcription."""
        return self.config.get("stt_language", "en")

    def get_stt_prompt(self) -> str:
        """Return an optional prompt for backends that support textual context."""
        return self.config.get("stt_prompt", "").strip()

    def get_stt_timeout_seconds(self) -> int:
        """Return the timeout for API-backed transcription requests."""
        return self.get_int_setting("stt_timeout_seconds", 30, min_value=1, max_value=600)

    def get_whisper_model(self) -> str:
        """Return the Whisper model to use for speech-to-text."""
        return self.config.get("whisper_model", "small.en")

    def get_whisper_device(self) -> str:
        """Return the device used for speech-to-text (GPU or CPU, defaults to GPU)."""
        return self.config.get("whisper_device", "GPU")

    def get_whisper_compute_type(self) -> str:
        """Return the compute type used when loading the Whisper model.

        ``auto``, ``default``, or a specific value such as ``int8_float16``. Defaults
        to ``default`` which for Whisper models is float16. See
        https://opennmt.net/CTranslate2/quantization.html#quantize-on-model-loading.
        """
        return self.config.get("whisper_compute_type", "default")

    def get_whisper_core_type(self) -> str:
        """Return the GPU core type used for the compute type.

        Tensor cores are available on devices with compute capability 7.0 or higher;
        ``tensor`` or ``standard``, defaults to ``tensor``.
        """
        return self.config.get("whisper_core_type", "tensor")

    def get_theme(self) -> str:
        """Return the configured UI theme name (``default``, ``dark``, or ``light``)."""
        return self.config.get("theme", _DEFAULT_THEME)

    def get_voiceattack_host(self) -> str:
        """Return the IP address of the machine running VoiceAttack (default localhost)."""
        host = self.config.get("voiceattack_host", VAIVOX.voiceattack_host)
        if not _is_loopback_host(host):
            logging.warning(
                "voiceattack_host is set to a non-local address (%s). VAIVOX commands "
                "are intended for localhost-only VoiceAttack plugin sockets.",
                host,
            )
        return host

    def get_voiceattack_port(self) -> int:
        """Return the port to connect to for VoiceAttack (default from ProductIdentity)."""
        return self.get_int_setting(
            "voiceattack_port", VAIVOX.voiceattack_port, min_value=1, max_value=65535
        )

    def get_control_host(self) -> str:
        """Return the localhost bind host for the inbound control socket."""
        return self.config.get("control_host", VAIVOX.control_host)

    def get_control_port(self) -> int:
        """Return the inbound control socket port."""
        return self.get_int_setting(
            "control_port", VAIVOX.control_port, min_value=1, max_value=65535
        )

    def get_api_host(self) -> str:
        """Return the localhost bind host for the introspection API."""
        return self.config.get("api_host", VAIVOX.api_host)

    def get_api_port(self) -> int:
        """Return the introspection API port."""
        return self.get_int_setting("api_port", VAIVOX.api_port, min_value=1, max_value=65535)

    def get_api_max_post_bytes(self) -> int:
        """Return the maximum accepted introspection POST body size."""
        return self.get_int_setting(
            "api_max_post_bytes",
            _DEFAULT_API_MAX_POST_BYTES,
            min_value=1024,
            max_value=1024 * 1024,
        )

    def get_text_line_length(self) -> int:
        """Return the line length for wrapping kneeboard note text (default 53)."""
        return self.get_int_setting("text_line_length", 53, min_value=10, max_value=200)
