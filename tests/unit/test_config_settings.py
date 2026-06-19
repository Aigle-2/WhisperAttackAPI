"""Unit tests for configuration safety and runtime fallback parsing."""

from __future__ import annotations

import logging

from vaivox.infrastructure.config.identity import VAIVOX
from vaivox.infrastructure.config.settings import VaivoxConfiguration


def _config(tmp_path, settings: str) -> VaivoxConfiguration:
    app_dir = tmp_path / "app"
    data_dir = tmp_path / "data"
    app_dir.mkdir()
    data_dir.mkdir()
    (app_dir / "settings.cfg").write_text(settings, encoding="utf-8")
    return VaivoxConfiguration(str(app_dir), str(data_dir))


def test_configuration_logs_redact_secret_values(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)

    config = _config(
        tmp_path,
        "\n".join(
            [
                "elevenlabs_api_key=super-secret-key",
                "api_token=local-token",
                "plain_setting=visible",
                "openai_api_key_env=OPENAI_API_KEY",
            ]
        ),
    )

    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-key" not in logs
    assert "local-token" not in logs
    assert "'elevenlabs_api_key': '<redacted>'" in logs
    assert "'api_token': '<redacted>'" in logs
    assert "'plain_setting': 'visible'" in logs
    assert config.get_safe_configuration()["openai_api_key_env"] == "OPENAI_API_KEY"


def test_invalid_critical_integers_fall_back_to_safe_defaults(tmp_path) -> None:
    config = _config(
        tmp_path,
        "\n".join(
            [
                "voiceattack_port=not-a-port",
                "control_port=70000",
                "api_port=0",
                "stt_timeout_seconds=-3",
                "text_line_length=2",
                "api_max_post_bytes=1",
            ]
        ),
    )

    assert config.get_voiceattack_port() == VAIVOX.voiceattack_port
    assert config.get_control_port() == VAIVOX.control_port
    assert config.get_api_port() == VAIVOX.api_port
    assert config.get_stt_timeout_seconds() == 30
    assert config.get_text_line_length() == 53
    assert config.get_api_max_post_bytes() == 16 * 1024


def test_non_local_voiceattack_host_is_warned(tmp_path, caplog) -> None:
    caplog.set_level(logging.WARNING)
    config = _config(tmp_path, "voiceattack_host=192.0.2.10\n")

    assert config.get_voiceattack_host() == "192.0.2.10"
    assert "non-local address" in caplog.text
