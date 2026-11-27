"""Client, CLI, and MCP contract tests using disposable DPAPI state and in-memory HTTP transport."""
from __future__ import annotations

import asyncio
import json
import secrets

import httpx
from mcp.server.mcpserver.exceptions import ToolError
import pytest

from flclash_control import cli, client as client_module, mcp_server
from flclash_control.client import PORT, ControlClient, ControlError


@pytest.fixture
def local_state(tmp_path):
    win32crypt = pytest.importorskip("win32crypt")
    token = secrets.token_urlsafe(32)
    encrypted = win32crypt.CryptProtectData(
        token.encode("utf-8"), "FlClash Control test", None, None, None, 0
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


def test_client_side_parameter_validation_stops_before_network(local_state):
    seen = []
    client = make_client(local_state, lambda req: seen.append(req))
    with pytest.raises(ControlError) as bad_action:
        client.call("arbitrary_rpc")
    assert bad_action.value.code == "unknown_action"

    with pytest.raises(ControlError) as bad_mode:
        client.call("mode", {"mode": "invalid"})
    assert bad_mode.value.code == "invalid_mode"

    with pytest.raises(ControlError) as bad_bool:
        client.call("tun", {"enabled": "yes"})
    assert bad_bool.value.code == "boolean_parameter_required"

    with pytest.raises(ControlError) as extra_param:
        client.call("status", {"unexpected": 1})
    assert extra_param.value.code == "unexpected_parameter"
    assert seen == []


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
    client = make_client(
        local_state,
        lambda _: httpx.Response(status, json={"ok": False, "error": secret, "detail": secret}),
    )
    with pytest.raises(ControlError) as failure:
        client.call("status")
    assert secret not in str(failure.value)


@pytest.mark.parametrize(
    ("status", "bridge_code"),
    [
        (409, "tun_authorization_or_apply_failed"),
        (409, "gui_not_initialized"),
        (429, "command_queue_full"),
        (503, "bridge_closing"),
        (500, "native_action_failed"),
    ],
)
def test_known_bridge_error_codes_produce_actionable_diagnostics(local_state, status, bridge_code):
    client = make_client(
        local_state,
        lambda _: httpx.Response(status, json={"ok": False, "error": bridge_code}),
    )
    with pytest.raises(ControlError) as failure:
        client.call("restart")
    assert failure.value.code == bridge_code
    assert bridge_code in str(failure.value)


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


def test_health_and_doctor_diagnostics(local_state, tmp_path):
    path, token, _ = local_state

    def healthy_handler(request):
        assert request.url == f"http://127.0.0.1:{PORT}/health"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={"ok": True, "bridge": "flclash-gui-control", "protocol": 1, "pid": 1234},
        )

    client = ControlClient(path, transport=httpx.MockTransport(healthy_handler))
    health = client.health()
    assert health == {"ok": True, "bridge": "flclash-gui-control", "protocol": 1, "port": PORT, "pid": 1234}

    diag = client.doctor()
    assert diag["ok"] is True
    assert diag["pid_matches"] is True
    assert token not in json.dumps(diag)

    mismatch_client = ControlClient(
        path,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"ok": True, "bridge": "flclash-gui-control", "protocol": 1, "pid": 9999},
            )
        ),
    )
    mismatch = mismatch_client.doctor()
    assert mismatch["ok"] is False and mismatch["pid_matches"] is False

    missing_client = ControlClient(
        tmp_path / "absent.json",
        transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("closed"))),
    )
    missing_diag = missing_client.doctor()
    assert missing_diag["ok"] is False and missing_diag["token_file_present"] is False


def test_exit_and_wait_polls_until_bridge_closes(local_state):
    health_calls = 0

    def handler(request):
        nonlocal health_calls
        if request.url.path == "/command":
            return httpx.Response(200, json={"ok": True, "data": {"exit_scheduled": True}})
        health_calls += 1
        if health_calls == 1:
            return httpx.Response(
                200,
                json={"ok": True, "bridge": "flclash-gui-control", "protocol": 1, "pid": 1234},
            )
        raise httpx.ConnectError("process exited")

    result = make_client(local_state, handler).exit_and_wait(wait_timeout=2.0, poll_interval=0.01)
    assert result == {"exit_scheduled": True, "exited": True}
    assert health_calls == 2


def test_env_configuration_overrides(local_state, monkeypatch):
    path, _, _ = local_state
    monkeypatch.setenv("FLCLASH_CONTROL_TOKEN_FILE", str(path))
    monkeypatch.setenv("FLCLASH_CONTROL_TIMEOUT", "12.5")
    c = ControlClient()
    assert c.token_path == path
    assert c.timeout == 12.5

    monkeypatch.setenv("FLCLASH_CONTROL_TIMEOUT", "-1")
    with pytest.raises(ControlError) as bad_timeout:
        ControlClient()
    assert bad_timeout.value.code == "invalid_timeout"


def test_cli_commands_and_error_exit_code(local_state, monkeypatch, capsys):
    path, _, _ = local_state

    class FakeClient:
        def __init__(self, token_path=None, *, timeout=None):
            self.token_path = token_path
            self.timeout = timeout

        def doctor(self):
            return {"ok": True, "bridge_pid": 1234}

        def call(self, action, params=None):
            if action == "restart":
                raise ControlError("Bridge busy", code="command_queue_full")
            return {"action": action, "params": params or {}}

    monkeypatch.setattr(cli, "ControlClient", FakeClient)
    assert cli.main(["--token-file", str(path), "doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert cli.main(["mode", "rule"]) == 0
    assert json.loads(capsys.readouterr().out) == {"action": "mode", "params": {"mode": "rule"}}

    assert cli.main(["restart"]) == 1
    assert "Bridge busy" in capsys.readouterr().err


def test_mcp_catalog_annotations_schema_and_error_wrapping(monkeypatch):
    tools = asyncio.run(mcp_server.mcp.list_tools())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == {
        "flclash_health",
        "flclash_status",
        "flclash_start",
        "flclash_stop",
        "flclash_restart_core",
        "flclash_set_tun",
        "flclash_set_system_proxy",
        "flclash_set_mode",
        "flclash_show_window",
        "flclash_exit",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.open_world_hint is False

    assert by_name["flclash_status"].annotations.read_only_hint is True
    assert by_name["flclash_health"].annotations.read_only_hint is True
    assert by_name["flclash_exit"].annotations.destructive_hint is True
    assert by_name["flclash_show_window"].annotations.destructive_hint is False
    mode_prop = by_name["flclash_set_mode"].input_schema["properties"]["mode"]
    assert set(mode_prop["enum"]) == {"rule", "global", "direct"}

    calls = []

    class FakeClient:
        def call(self, action, params=None):
            calls.append((action, params))
            if action == "restart":
                raise ControlError("Bridge unavailable", code="bridge_unavailable")
            return {"system_proxy": True}

    monkeypatch.setattr(mcp_server, "ControlClient", FakeClient)
    assert mcp_server.flclash_set_system_proxy(True) == {"system_proxy": True}
    assert calls == [("system-proxy", {"enabled": True})]

    with pytest.raises(ToolError, match="Bridge unavailable"):
        mcp_server.flclash_restart_core()
