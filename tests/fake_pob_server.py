"""A tiny stand-in for pob-mcp, so the pool can be tested over real MCP stdio."""

import json
import sys
import time

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # pragma: no cover - SDK 1.x
    from mcp.server.fastmcp import FastMCP

server = FastMCP("fake-pob")
state: dict = {"ascendancy": None, "log": []}


@server.tool()
def new_build(ascendancy: str | None = None) -> dict:
    state["ascendancy"] = ascendancy
    return {"ascendancy": ascendancy}


@server.tool()
def get_build_summary() -> dict:
    return {"ascendancy": state["ascendancy"]}


@server.tool()
def load_build(source: str, name: str | None = None) -> dict:
    state["log"].append({"load_build": {"source": source, "name": name}})
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
def received() -> str:
    return json.dumps(state["log"])


if __name__ == "__main__":
    server.run("stdio")
    sys.exit(0)
