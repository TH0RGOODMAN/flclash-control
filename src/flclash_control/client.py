"""Authenticated client for the local control bridge hosted by the running FlClash GUI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

import httpx

PORT = 47892
MAX_RESPONSE = 128 * 1024
VALID_MODES: frozenset[str] = frozenset({"rule", "global", "direct"})
VALID_ACTIONS: frozenset[str] = frozenset({
    "status",
    "start",
    "stop",
    "restart",
    "tun",
    "system-proxy",
    "system_proxy",
    "mode",
    "show",
    "exit",
})

# Strict allowlist of fixed error codes emitted by control_bridge.dart.
# Unknown response bodies are never echoed so credentials/URLs cannot leak.
KNOWN_BRIDGE_ERRORS: dict[str, str] = {
    "bridge_closing": "FlClash control bridge is shutting down (bridge_closing).",
    "local_clients_only": "FlClash bridge rejected non-loopback or unexpected Host header (local_clients_only).",
    "browser_origin_denied": "FlClash bridge rejected browser Origin/Fetch-Metadata headers (browser_origin_denied).",
    "not_found": "FlClash bridge endpoint was not found (not_found).",
    "authentication_failed": "FlClash bridge authorization failed; retry after the GUI has finished starting (authentication_failed).",
    "json_required": "FlClash bridge requires application/json content type (json_required).",
    "invalid_body_size": "FlClash bridge rejected invalid request body size (invalid_body_size).",
    "body_too_large": "FlClash bridge rejected oversized request body (body_too_large).",
    "invalid_command": "FlClash bridge rejected malformed command payload (invalid_command).",
    "command_queue_full": "FlClash bridge command queue is full; wait for pending operations to finish (command_queue_full).",
    "invalid_json": "FlClash bridge rejected invalid JSON payload (invalid_json).",
    "request_body_timeout": "FlClash bridge timed out while reading request body (request_body_timeout).",
    "gui_not_initialized": "FlClash GUI has not finished native initialization yet (gui_not_initialized).",
    "listeners_did_not_start": "FlClash native proxy listeners failed to start (listeners_did_not_start).",
    "listeners_did_not_stop": "FlClash native proxy listeners failed to stop (listeners_did_not_stop).",
    "restart_state_not_restored": "FlClash core restarted, but previous listener state could not be restored (restart_state_not_restored).",
    "tun_authorization_or_apply_failed": "FlClash TUN authorization or configuration failed; check UAC prompt or Helper service (tun_authorization_or_apply_failed).",
    "invalid_mode": "Invalid outbound mode; expected rule, global, or direct (invalid_mode).",
    "preference_save_failed": "FlClash failed to persist GUI configuration to disk (preference_save_failed).",
    "unknown_action": "FlClash bridge does not recognize the requested action (unknown_action).",
    "system_proxy_apply_failed": "FlClash native system-proxy plugin failed to apply state (system_proxy_apply_failed).",
    "native_core_not_ready": "FlClash native core is not connected or initialized (native_core_not_ready).",
    "unexpected_parameter": "FlClash bridge rejected unexpected command parameters (unexpected_parameter).",
    "boolean_parameter_required": "FlClash bridge requires a boolean parameter (boolean_parameter_required).",
    "native_action_failed": "FlClash native action failed; inspect GUI state before retrying (native_action_failed).",
}


class ControlError(RuntimeError):
    """Safe client/bridge error that never embeds raw response payloads or tokens."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def default_token_path() -> Path:
    override = os.environ.get("FLCLASH_CONTROL_TOKEN_FILE", "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "FlClash-Control" / "gui-bridge.json"


def _default_timeout() -> float:
    raw = os.environ.get("FLCLASH_CONTROL_TIMEOUT", "").strip()
    if not raw:
        return 45.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ControlError("FLCLASH_CONTROL_TIMEOUT must be a positive number.", code="invalid_timeout") from exc
    if value <= 0 or value > 600:
        raise ControlError("FLCLASH_CONTROL_TIMEOUT must be between 0 and 600 seconds.", code="invalid_timeout")
    return value


def _extract_safe_bridge_code(response: httpx.Response) -> str | None:
    if len(response.content) > MAX_RESPONSE:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    err = payload.get("error")
    if isinstance(err, str) and err in KNOWN_BRIDGE_ERRORS:
        return err
    return None


class ControlClient:
    def __init__(
        self,
        token_path: Path | str | None = None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token_path = Path(token_path) if token_path is not None else default_token_path()
        self.timeout = _default_timeout() if timeout is None else timeout
        self.transport = transport

    def _read_state_and_token(self) -> tuple[dict[str, Any], str]:
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("protected_token"), str):
                raise ValueError("Invalid bridge state")
            if data.get("protocol") != 1 or data.get("port") != PORT:
                raise ValueError("Invalid bridge state")
            import win32crypt

            token = win32crypt.CryptUnprotectData(
                bytes.fromhex(data["protected_token"]), None, None, None, 0
            )[1].decode("utf-8")
            if len(token) < 32:
                raise ValueError("Invalid bridge authorization")
            return data, token
        except Exception as exc:
            raise ControlError(
                "FlClash control bridge is unavailable. Start the bridge-enabled FlClash build.",
                code="bridge_unavailable",
            ) from exc

    def _token(self) -> str:
        _, token = self._read_state_and_token()
        return token

    def _http_client(self, *, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=f"http://127.0.0.1:{PORT}",
            timeout=self.timeout if timeout is None else timeout,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _validate_request(action: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if action not in VALID_ACTIONS:
            raise ControlError(f"Unsupported control action: {action}", code="unknown_action")
        wire_action = "system_proxy" if action == "system-proxy" else action
        if wire_action in {"tun", "system_proxy"}:
            if set(params.keys()) != {"enabled"} or not isinstance(params.get("enabled"), bool):
                raise ControlError(
                    f"Action '{action}' requires a boolean 'enabled' parameter.",
                    code="boolean_parameter_required",
                )
        elif wire_action == "mode":
            if set(params.keys()) != {"mode"} or params.get("mode") not in VALID_MODES:
                raise ControlError(
                    "Invalid outbound mode; expected rule, global, or direct.",
                    code="invalid_mode",
                )
        elif params:
            raise ControlError(
                f"Action '{action}' does not accept extra parameters.",
                code="unexpected_parameter",
            )
        return wire_action, params

    def health(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Probe unauthenticated loopback GET /health without exposing any credentials."""
        try:
            with self._http_client(timeout=timeout) as client:
                response = client.get("/health")
            if response.status_code < 200 or response.status_code >= 300:
                code = _extract_safe_bridge_code(response)
                if code:
                    raise ControlError(KNOWN_BRIDGE_ERRORS[code], code=code)
                raise ControlError(
                    f"FlClash bridge health check failed (HTTP {response.status_code}).",
                    code="health_http_error",
                )
            if len(response.content) > MAX_RESPONSE:
                raise ControlError("Unexpectedly large control response", code="response_too_large")
            data = response.json()
        except ControlError:
            raise
        except httpx.TimeoutException as exc:
            raise ControlError("FlClash bridge health check timed out.", code="health_timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ControlError("Cannot reach the running FlClash control bridge.", code="bridge_unreachable") from exc

        pid = data.get("pid") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or data.get("ok") is not True
            or data.get("bridge") != "flclash-gui-control"
            or data.get("protocol") != 1
            or not isinstance(pid, int)
            or isinstance(pid, bool)
        ):
            raise ControlError("Unexpected response from loopback port 47892.", code="invalid_health_response")
        return {
            "ok": True,
            "bridge": "flclash-gui-control",
            "protocol": 1,
            "port": PORT,
            "pid": pid,
        }

    def doctor(self, *, timeout: float = 5.0) -> dict[str, Any]:
        """Diagnose local DPAPI state file and live bridge health without leaking secrets."""
        state_exists = self.token_path.is_file()
        state_pid: int | None = None
        dpapi_valid = False
        if state_exists:
            try:
                state_data, _ = self._read_state_and_token()
                dpapi_valid = True
                raw_pid = state_data.get("pid")
                if isinstance(raw_pid, int) and not isinstance(raw_pid, bool):
                    state_pid = raw_pid
            except ControlError:
                dpapi_valid = False

        bridge_reachable = False
        live_pid: int | None = None
        health_error: str | None = None
        try:
            health_info = self.health(timeout=timeout)
            bridge_reachable = True
            live_pid = health_info["pid"]
        except ControlError as exc:
            health_error = exc.code or "bridge_unreachable"

        pid_matches = (state_pid == live_pid) if (state_pid is not None and live_pid is not None) else None
        ready = dpapi_valid and bridge_reachable and (pid_matches is not False)
        return {
            "ok": ready,
            "port": PORT,
            "token_file_present": state_exists,
            "dpapi_authorized": dpapi_valid,
            "bridge_reachable": bridge_reachable,
            "state_pid": state_pid,
            "bridge_pid": live_pid,
            "pid_matches": pid_matches,
            "error": None if ready else (health_error or ("dpapi_unavailable" if state_exists else "state_file_missing")),
        }

    def call(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        wire_action, clean_params = self._validate_request(action, params or {})
        token = self._token()
        try:
            with self._http_client() as client:
                response = client.post(
                    "/command",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"action": wire_action, "params": clean_params},
                )
            if response.status_code in (401, 403):
                code = _extract_safe_bridge_code(response) or "authentication_failed"
                raise ControlError(KNOWN_BRIDGE_ERRORS[code], code=code)
            if response.status_code < 200 or response.status_code >= 300:
                code = _extract_safe_bridge_code(response)
                if code is not None:
                    raise ControlError(KNOWN_BRIDGE_ERRORS[code], code=code)
                raise ControlError(
                    f"FlClash bridge rejected the command (HTTP {response.status_code}).",
                    code="http_error",
                )
            if len(response.content) > MAX_RESPONSE:
                raise ControlError("Unexpectedly large control response", code="response_too_large")
            data = response.json()
        except ControlError:
            raise
        except httpx.TimeoutException as exc:
            raise ControlError(
                "FlClash command outcome is unknown after timeout. Check status before retrying; native authorization may still be pending.",
                code="command_timeout",
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ControlError("Cannot reach the running FlClash control bridge.", code="bridge_unreachable") from exc
        if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("data"), dict):
            raise ControlError("FlClash did not complete the requested control action.", code="malformed_response")
        return data["data"]

    def exit_and_wait(self, *, wait_timeout: float = 10.0, poll_interval: float = 0.25) -> dict[str, Any]:
        """Schedule normal GUI exit and poll /health until the bridge closes or timeout expires."""
        result = dict(self.call("exit"))
        deadline = time.monotonic() + max(0.5, wait_timeout)
        exited = False
        while time.monotonic() < deadline:
            try:
                self.health(timeout=min(1.0, max(0.2, deadline - time.monotonic())))
            except ControlError:
                exited = True
                break
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        result["exited"] = exited
        return result
