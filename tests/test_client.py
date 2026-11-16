"""Client contract tests using disposable DPAPI state and an in-memory HTTP server."""
from __future__ import annotations

import asyncio
import json
import secrets

import httpx
import pytest

from flclash_control import client as client_module
from flclash_control.client import ControlClient, ControlError, PORT


@pytest.fixture
def local_state(tmp_path):
    win32crypt = pytest.importorskip("win32crypt")
    token = secrets.token_urlsafe(32)
    encrypted = win32crypt.CryptProtectData(
        token.encode(), "FlClash Control test", None, None, None, 0
    )
    path = tmp_path / "gui-bridge.json"
    state = {
        "protocol": 1,
        "port": PORT,
        "pid": 1234,
        "protected_token": encrypted.hex(),
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    return path, token, state


def make_client(local_state, handler):
    return ControlClient(local_state[0], transport=httpx.MockTransport(handler))


def test_real_dpapi_decryption_and_loopback_request(local_state):
    path, token, _ = local_state
    assert token not in path.read_text(encoding="utf-8")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "data": {"running": True}})

    assert make_client(local_state, handler).call("status") == {"running": True}
    assert len(requests) == 1
    request = requests[0]
    assert request.url == f"http://127.0.0.1:{PORT}/command"
    assert request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {token}"
    assert request.headers["host"] == f"127.0.0.1:{PORT}"
    assert "origin" not in request.headers
    assert json.loads(request.content) == {"action": "status", "params": {}}


@pytest.mark.parametrize(
    ("action", "params", "wire_action"),
    [
        ("system-proxy", {"enabled": True}, "system_proxy"),
        ("tun", {"enabled": False}, "tun"),
        ("mode", {"mode": "rule"}, "mode"),
        ("restart", None, "restart"),
    ],
)
def test_command_body_mapping(local_state, action, params, wire_action):
    def handler(request):
        assert json.loads(request.content) == {
            "action": wire_action,
            "params": params or {},
        }
        return httpx.Response(200, json={"ok": True, "data": {}})

    assert make_client(local_state, handler).call(action, params) == {}


def test_http_client_ignores_environment_proxies(local_state, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.1:1")
    original = httpx.Client
    options = []

    def record_client(*args, **kwargs):
        options.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", record_client)
    client = make_client(
        local_state,
        lambda _: httpx.Response(200, json={"ok": True, "data": {}}),
    )
    client.call("status")
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["base_url"] == f"http://127.0.0.1:{PORT}"


@pytest.mark.parametrize("status", [401, 403, 409, 500])
def test_http_failure_does_not_echo_response_or_token(local_state, status):
    secret = local_state[1]
    client = make_client(local_state, lambda _: httpx.Response(status, text=secret))
    with pytest.raises(ControlError) as failure:
        client.call("status")
    assert secret not in str(failure.value)


def test_redirect_is_not_followed(local_state):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://example.invalid/collect"})

    with pytest.raises(ControlError):
        make_client(local_state, handler).call("restart")
    assert seen == [f"http://127.0.0.1:{PORT}/command"]


def test_redirect_body_cannot_be_accepted_as_success(local_state):
    client = make_client(
        local_state,
        lambda _: httpx.Response(
            307,
            headers={"location": "https://example.invalid/collect"},
            json={"ok": True, "data": {"running": True}},
        ),
    )
    with pytest.raises(ControlError):
        client.call("status")


@pytest.mark.parametrize(
    "body",
    [[], {"ok": False, "data": {}}, {"ok": True, "data": []}, {"ok": "true", "data": {}}],
)
def test_malformed_response_is_not_success(local_state, body):
    with pytest.raises(ControlError):
        make_client(local_state, lambda _: httpx.Response(200, json=body)).call("status")


def test_response_size_limit(local_state):
    with pytest.raises(ControlError, match="large"):
        make_client(
            local_state,
            lambda _: httpx.Response(200, content=b"x" * (client_module.MAX_RESPONSE + 1)),
        ).call("status")


@pytest.mark.parametrize(
    "exception",
    [httpx.ConnectError("connect failed"), httpx.ReadTimeout("operation outcome unknown")],
)
def test_transport_errors_become_control_errors(local_state, exception):
    def handler(_):
        raise exception

    with pytest.raises(ControlError) as failure:
        make_client(local_state, handler).call("restart")
    assert local_state[1] not in str(failure.value)


@pytest.mark.parametrize(
    "state",
    [
        [],
        {"protocol": 2, "port": PORT, "protected_token": "00"},
        {"protocol": 1, "port": 9090, "protected_token": "00"},
        {"protocol": 1, "port": PORT, "protected_token": None},
        {"protocol": 1, "port": PORT, "protected_token": "not hex"},
        {"protocol": 1, "port": PORT, "protected_token": "00"},
    ],
)
def test_invalid_local_state_fails_before_network(tmp_path, state):
    path = tmp_path / "invalid-state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    seen = []
    client = ControlClient(path, transport=httpx.MockTransport(lambda request: seen.append(request)))
    with pytest.raises(ControlError):
        client.call("restart")
    assert not seen


def test_missing_local_state_is_controlled_error(tmp_path):
    with pytest.raises(ControlError):
        ControlClient(tmp_path / "missing.json").call("status")


def test_mcp_catalog_exposes_only_gui_control_tools():
    from flclash_control.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "flclash_status", "flclash_start", "flclash_stop", "flclash_restart_core",
        "flclash_set_tun", "flclash_set_system_proxy", "flclash_set_mode",
        "flclash_show_window", "flclash_exit",
    }
    status = next(tool for tool in tools if tool.name == "flclash_status")
    assert status.annotations.read_only_hint is True


def test_mcp_system_proxy_mapping(monkeypatch):
    from flclash_control import mcp_server

    calls = []

    class FakeClient:
        def call(self, action, params=None):
            calls.append((action, params))
            return {"system_proxy": True}

    monkeypatch.setattr(mcp_server, "ControlClient", FakeClient)
    assert mcp_server.flclash_set_system_proxy(True) == {"system_proxy": True}
    assert calls == [("system-proxy", {"enabled": True})]
