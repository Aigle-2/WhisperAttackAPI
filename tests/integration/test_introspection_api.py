"""Integration tests for the localhost introspection API (ADR-0010).

Start the real stdlib HTTP server on an ephemeral port and exercise it over HTTP —
status, dry-run reconcile, auth, and error paths — with in-memory fakes for the ports.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from vaivox.application.queries import DescribeStatus, DryRunReconcile
from vaivox.infrastructure.api.introspection import IntrospectionServer

FUZZY_WORDS = ["Kobuleti", "Senaki"]


class FakeRecorder:
    def __init__(self, recording=False):
        self._recording = recording

    @property
    def is_recording(self):
        return self._recording


class FakeConfig:
    def get_word_mappings(self):
        return {}

    def get_fuzzy_words(self):
        return FUZZY_WORDS

    def get_safe_configuration(self):
        return {"stt_backend": "elevenlabs", "elevenlabs_api_key": "<redacted>"}

    def get_stt_backend(self):
        return "elevenlabs"


def _make_server(token=None):
    config = FakeConfig()
    return IntrospectionServer(
        DescribeStatus(FakeRecorder(), config),
        DryRunReconcile(config),
        host="127.0.0.1",
        port=0,
        token=token,
    )


def _get(host, port, path, token=None):
    request = urllib.request.Request(f"http://{host}:{port}{path}")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post(host, port, path, body, token=None):
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method="POST")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


@pytest.fixture
def server():
    instance = _make_server()
    host, port = instance.start()
    yield host, port
    instance.stop()


def test_healthz_returns_ok(server):
    host, port = server

    status, payload = _get(host, port, "/healthz")

    assert status == 200
    assert payload == {"status": "ok"}


def test_status_reports_state_with_redacted_config(server):
    host, port = server

    status, payload = _get(host, port, "/status")

    assert status == 200
    assert payload["recording"] is False
    assert payload["stt_backend"] == "elevenlabs"
    assert payload["config"]["elevenlabs_api_key"] == "<redacted>"
    assert "version" in payload


def test_dry_run_reconcile_returns_pipeline_stages(server):
    host, port = server

    status, payload = _post(host, port, "/reconcile/dry-run", {"text": "kobuletti tower"})

    assert status == 200
    assert payload["raw_text"] == "kobuletti tower"
    assert payload["command_text"] == "Kobuleti tower"


def test_dry_run_without_text_is_bad_request(server):
    host, port = server

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _post(host, port, "/reconcile/dry-run", {"not_text": 1})

    assert exc_info.value.code == 400


def test_unknown_path_is_not_found(server):
    host, port = server

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        _get(host, port, "/does-not-exist")

    assert exc_info.value.code == 404


def test_bearer_token_is_enforced_when_configured():
    instance = _make_server(token="s3cret")
    host, port = instance.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(host, port, "/status")
        assert exc_info.value.code == 401

        status, _payload = _get(host, port, "/status", token="s3cret")
        assert status == 200
    finally:
        instance.stop()
