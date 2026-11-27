"""MCP tools calling the running FlClash GUI's own native control actions."""
from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .client import ControlClient, ControlError

mcp = MCPServer(
    "flclash-control",
    version=__version__,
    title="FlClash Control",
    website_url="https://github.com/TH0RGOODMAN/flclash-control",
    instructions=(
        "Controls the running bridge-enabled FlClash Windows GUI. "
        "Settings are applied through FlClash's Riverpod state/actions and persisted to GUI preferences. "
        "No mouse or keyboard input is injected. Native UAC permission prompts still require the local user; "
        "if a mutation times out, call flclash_status before retrying."
    ),
)


def _run(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except ControlError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(
    annotations=ToolAnnotations(
        title="Check Bridge Health",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_health() -> dict[str, Any]:
    """Diagnose local DPAPI authorization state and loopback bridge reachability without sending a control mutation."""
    return _run(lambda: ControlClient().doctor())


@mcp.tool(
    annotations=ToolAnnotations(
        title="Read FlClash Status",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_status() -> dict[str, Any]:
    """Read GUI initialization, core connection, listener run state, TUN, system proxy, outbound mode, and pending queue state."""
    return _run(lambda: ControlClient().call("status"))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Start Proxy Listeners",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_start() -> dict[str, Any]:
    """Start FlClash listeners and synchronize current GUI settings through its native action."""
    return _run(lambda: ControlClient().call("start"))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Stop Proxy Listeners",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_stop() -> dict[str, Any]:
    """Stop FlClash proxy listeners through its native action while keeping the GUI process and control bridge open."""
    return _run(lambda: ControlClient().call("stop"))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Restart Native Core",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
def flclash_restart_core() -> dict[str, Any]:
    """Reconnect Helper/IPC and reinitialize FlClashCore through the GUI's native restart flow, preserving running/stopped state."""
    return _run(lambda: ControlClient().call("restart"))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set TUN Mode",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_set_tun(enabled: bool) -> dict[str, Any]:
    """Enable or disable the GUI's TUN switch, applying native permission checks and persisting the preference."""
    return _run(lambda: ControlClient().call("tun", {"enabled": enabled}))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set Windows System Proxy",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_set_system_proxy(enabled: bool) -> dict[str, Any]:
    """Enable or disable the GUI's Windows system-proxy switch through its native proxy plugin and save preferences."""
    return _run(lambda: ControlClient().call("system-proxy", {"enabled": enabled}))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Set Outbound Mode",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_set_mode(mode: Literal["rule", "global", "direct"]) -> dict[str, Any]:
    """Switch outbound routing mode (rule, global, or direct) in the GUI and persist to preferences."""
    return _run(lambda: ControlClient().call("mode", {"mode": mode}))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Show FlClash Window",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def flclash_show_window() -> dict[str, Any]:
    """Reveal the existing FlClash GUI window without injecting desktop mouse or keyboard input."""
    return _run(lambda: ControlClient().call("show"))


@mcp.tool(
    annotations=ToolAnnotations(
        title="Exit FlClash GUI",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
def flclash_exit(wait_for_exit: bool = False) -> dict[str, Any]:
    """Save GUI preferences and normally exit FlClash and its core; optionally wait for bridge shutdown."""
    if wait_for_exit:
        return _run(lambda: ControlClient().exit_and_wait())
    return _run(lambda: ControlClient().call("exit"))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
