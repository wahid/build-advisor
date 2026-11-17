"""A tiny stand-in for pob-mcp, so the pool can be tested over real MCP stdio."""

import json
import sys
import time

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - SDK 1.x
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

server = FastMCP("fake-pob")
state: dict = {"ascendancy": None, "log": [], "resets": 0}


@server.tool()
def new_build(ascendancy: str | None = None) -> dict:
    if state.get("crashed_on_reset"):
        state["crashed"] = True
        get_stats()
    state["ascendancy"] = ascendancy
    state["resets"] += 1
    return {"ascendancy": ascendancy}


@server.tool()
def resets() -> int:
    return state["resets"]


@server.tool()
def get_build_summary() -> dict:
    return {"ascendancy": state["ascendancy"]}


@server.tool()
def load_build(source: str, name: str | None = None) -> dict:
    state["log"].append({"load_build": {"source": source, "name": name}})
    if source == "newer-tree":
        # What Path of Building does with a passive tree version it doesn't know: an
        # empty character, no error, and a crash on the next reset.
        state["crashed_on_reset"] = True
        return {"className": "Scion", "level": 92, "passivePointsUsed": 0, "treeVersion": "3_29"}
    return {"loaded": source[:20]}


@server.tool()
def export_build(format: str = "code", save_to: str | None = None) -> dict:
    return {"code": "eNrFAKE", "format": format, "save_to": save_to}


@server.tool()
def save_to_pob(name: str) -> dict:  # not on the allowlist
    return {"saved": name}


@server.tool()
def slow(seconds: float) -> dict:
    time.sleep(seconds)
    return {"slept": seconds}


@server.tool()
def fail() -> dict:
    raise ValueError("PoB says no")


@server.tool()
def crash() -> dict:
    """Path of Building's crash screen: from then on every call reports it."""
    state["crashed"] = True
    return get_stats()


@server.tool()
def get_stats() -> dict:
    if state.get("crashed"):
        raise ToolError(
            "Error:  In 'OnFrame': Modules/Build.lua:872: attempt to index a nil value v2.67.2 "
            "Press Enter/Escape to dismiss, F4 to return to build selection."
        )
    return {"Life": 5000}


@server.tool()
def received() -> str:
    return json.dumps(state["log"])


if __name__ == "__main__":
    server.run("stdio")
    sys.exit(0)
