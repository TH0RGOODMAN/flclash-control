"""MCP tools calling the running FlClash GUI's own control actions."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from .client import ControlClient

mcp = MCPServer("flclash-control", version="0.1.0", instructions="Controls the running bridge-enabled FlClash GUI. Settings are applied through the GUI state/actions and saved there. No mouse or keyboard input is injected. Native permission prompts still require the user.")

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def flclash_status() -> dict:
    """Read GUI, core, TUN, system proxy and outbound-mode state."""
    return ControlClient().call("status")

@mcp.tool()
def flclash_start() -> dict:
    """Start FlClash through its GUI's native action."""
    return ControlClient().call("start")

@mcp.tool()
def flclash_stop() -> dict:
    """Stop FlClash listeners through its native action; keep the GUI open."""
    return ControlClient().call("stop")

@mcp.tool()
def flclash_restart_core() -> dict:
    """Reconnect Helper/IPC and reinitialize the core through the GUI's native restart action."""
    return ControlClient().call("restart")

@mcp.tool()
def flclash_set_tun(enabled: bool) -> dict:
    """Set and save the GUI's TUN switch, applying its native permission checks."""
    return ControlClient().call("tun", {"enabled": enabled})

@mcp.tool()
def flclash_set_system_proxy(enabled: bool) -> dict:
    """Set and save the GUI's system-proxy option and apply its native proxy plugin."""
    return ControlClient().call("system-proxy", {"enabled": enabled})

@mcp.tool()
def flclash_set_mode(mode: str) -> dict:
    """Set and save rule/global/direct outbound mode in the GUI."""
    return ControlClient().call("mode", {"mode": mode})

@mcp.tool()
def flclash_show_window() -> dict:
    """Show the existing GUI window without injecting desktop input."""
    return ControlClient().call("show")

@mcp.tool()
def flclash_exit() -> dict:
    """Save settings and normally exit the GUI and its core."""
    return ControlClient().call("exit")

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
