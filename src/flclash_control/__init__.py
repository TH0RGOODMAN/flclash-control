"""FlClash Control: authenticated CLI and MCP control without desktop input injection."""
from __future__ import annotations

from .client import PORT, ControlClient, ControlError, default_token_path

__version__ = "0.2.0"
__all__ = ["PORT", "__version__", "ControlClient", "ControlError", "default_token_path"]
