"""Unit tests for the plugin runtime-health compatibility verdict."""

from __future__ import annotations

import dataclasses

import pytest

from vaivox.domain.plugin.model import (
    PluginCompatibility,
    PluginHandshake,
    evaluate_compatibility,
)


def test_no_handshake_is_unknown() -> None:
    assert evaluate_compatibility(None, app_protocol_version=1) == PluginCompatibility.UNKNOWN


def test_matching_protocol_is_up_to_date() -> None:
    handshake = PluginHandshake(plugin_version="1.0.0.0", protocol_version=1)

    assert (
        evaluate_compatibility(handshake, app_protocol_version=1) == PluginCompatibility.UP_TO_DATE
    )


def test_differing_protocol_is_mismatch() -> None:
    handshake = PluginHandshake(plugin_version="1.0.0.0", protocol_version=2)

    assert (
        evaluate_compatibility(handshake, app_protocol_version=1)
        == PluginCompatibility.PROTOCOL_MISMATCH
    )


def test_build_version_does_not_affect_verdict() -> None:
    # The plugin build string is a separate release line from the app; only the wire
    # protocol version gates compatibility, so any build with a matching protocol is
    # up to date (and any build with a differing protocol is a mismatch).
    newer_build = PluginHandshake(plugin_version="9.9.9.9", protocol_version=1)
    older_build = PluginHandshake(plugin_version="0.0.0.1", protocol_version=1)

    assert (
        evaluate_compatibility(newer_build, app_protocol_version=1)
        == PluginCompatibility.UP_TO_DATE
    )
    assert (
        evaluate_compatibility(older_build, app_protocol_version=1)
        == PluginCompatibility.UP_TO_DATE
    )


def test_handshake_is_immutable() -> None:
    handshake = PluginHandshake(plugin_version="1.0.0.0", protocol_version=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        handshake.protocol_version = 2  # type: ignore[misc]
