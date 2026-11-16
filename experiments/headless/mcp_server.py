"""MCP tools for an explicitly started headless native FlClash host."""
from __future__ import annotations
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from .service import BridgeClient

mcp = MCPServer("flclash-control", version="0.1.0", instructions="Requires flclash-control serve. GUI and headless host must run separately. These tools call the native Helper/IPC bridge, not desktop UI input.")

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def flclash_native_status() -> dict:
    """Get the initialized/running/TUN/mode state of the native headless core."""
    return BridgeClient().call("status")

@mcp.tool()
def flclash_native_start() -> dict:
    """Start proxy and TUN listeners in the existing headless host."""
    return BridgeClient().call("start")

@mcp.tool()
def flclash_native_stop() -> dict:
    """Stop listeners while keeping the headless management bridge alive."""
    return BridgeClient().call("stop")

@mcp.tool()
def flclash_native_restart() -> dict:
    """Recreate the core through Helper, reconnect private IPC, initialize and restore runtime state."""
    return BridgeClient().call("restart")

@mcp.tool()
def flclash_native_tun(enabled: bool) -> dict:
    """Set the headless TUN state; does not change GUI preferences."""
    return BridgeClient().call("tun", {"enabled": enabled})

@mcp.tool()
def flclash_native_mode(mode: str) -> dict:
    """Set headless outbound mode: rule, global or direct."""
    return BridgeClient().call("mode", {"mode": mode})

@mcp.tool()
def flclash_native_release() -> dict:
    """Release the headless core and bridge so the GUI can be reopened normally."""
    return BridgeClient().call("release")

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
