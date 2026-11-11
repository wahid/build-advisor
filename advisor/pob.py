"""Path of Building tools for the LLM, through the pob-mcp MCP server.

pob-mcp runs Path of Building's own calculation engine. It keeps one loaded
build per process and needs ~5 s to boot, so a small pool of server processes
is kept running. Each question checks one out, resets it with `new_build`
(so nobody sees the previous visitor's build) and returns it afterwards.

The MCP client is async; it runs in one background event-loop thread, and
each server lives in its own long-running task there (anyio requires entering
and leaving the stdio context in the same task).

Because questions come from the public internet, the model only gets an
allowlist of tools, and arguments that touch the server's file system are
removed or validated.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)

# Tools the model may call. Left out on purpose: poe.ninja ladder tools (they use
# poe.ninja's internal builds API, which isn't open to third parties), anything
# reading or writing files or PoB's Builds folder, character import, images.
DEFAULT_TOOLS = (
    "load_build",
    "new_build",
    "get_build_summary",
    "get_stats",
    "get_skills",
    "get_items",
    "get_passive_tree",
    "get_config",
    "get_warnings",
    "explain_stat",
    "evaluate_scenarios",
    "rank_support_gems",
    "rank_passives",
    "compare_changes",
    "apply_changes",
    "undo_last_change",
    "auto_allocate_passives",
    "search_gems",
    "search_uniques",
    "list_classes",
    "list_ascendancy_notables",
    "list_keystones",
    "find_passive_nodes",
    "fix_gaps",
    "export_build",
    "price_check",
)

# Tools that only read the build, or try a change and put the build back exactly as
# it was. Any other tool may change the loaded build.
READ_ONLY_TOOLS = frozenset(
    {
        "get_build_summary",
        "get_stats",
        "get_skills",
        "get_items",
        "get_passive_tree",
        "get_config",
        "get_warnings",
        "explain_stat",
        "evaluate_scenarios",
        "rank_support_gems",
        "rank_passives",
        "compare_changes",
        "search_gems",
        "search_uniques",
        "list_classes",
        "list_ascendancy_notables",
        "list_keystones",
        "find_passive_nodes",
        "export_build",
        "price_check",
    }
)

# Tools that work without a loaded build (they start one or look things up).
NO_BUILD_NEEDED = frozenset(
    {
        "new_build",
        "load_build",
        "search_gems",
        "search_uniques",
        "list_classes",
        "list_ascendancy_notables",
        "list_keystones",
        "find_passive_nodes",
        "price_check",
    }
)
NO_BUILD_ERROR = (
    "No build is loaded. Ask the user to attach their build (a pobb.in or pastebin "
    "link, or a Path of Building share code), or create one with new_build."
)

SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9_\-+/=]{100,}$")
BUILD_LINK_HOSTS = {"pobb.in", "pastebin.com", "www.pastebin.com"}
BUILD_LINK_RE = re.compile(r"https?://(?:www\.)?(?:pobb\.in|pastebin\.com)/[\w\-/]+", re.IGNORECASE)
LINK_ONLY_QUESTION = "What do you think of this build?"
MAX_DESCRIPTION = 2000


class PobUnavailable(RuntimeError):
    """Path of Building can't be used right now (not installed, busy, crashed)."""


class PobToolError(RuntimeError):
    """A tool call was rejected or failed; the message is shown to the model."""


# --- argument safety ------------------------------------------------------------


def validate_build_source(source: str) -> str:
    """Accept only PoB share codes and pobb.in / pastebin links (no paths, no XML)."""
    compact = re.sub(r"\s+", "", source)
    if SHARE_CODE_RE.match(compact):
        return compact
    url = urlparse(source.strip())
    if url.scheme == "https" and url.hostname in BUILD_LINK_HOSTS and url.path.strip("/"):
        return source.strip()
    raise PobToolError(
        "Only Path of Building share codes and https links to pobb.in or pastebin.com "
        "can be loaded."
    )


def split_build_link(question: str) -> tuple[str, str]:
    """Take a pobb.in / pastebin link out of a question: (question without it, link).

    A question that was only the link becomes a general question about the build.
    """
    match = BUILD_LINK_RE.search(question)
    if not match:
        return question, ""
    link = re.sub(r"^http://", "https://", match.group(0).rstrip("/"), flags=re.IGNORECASE)
    rest = re.sub(r"\s{2,}", " ", question[: match.start()] + question[match.end() :]).strip()
    return (rest if re.search(r"\w", rest) else LINK_ONLY_QUESTION), link


def sanitize_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "load_build":
        return {"source": validate_build_source(str(arguments.get("source", "")))}
    if name == "export_build":
        return {"format": "code"}  # never `save_to`, never XML
    return arguments


def openai_tool_definitions(mcp_tools: list[Any], allowed: set[str]) -> list[dict[str, Any]]:
    """Convert MCP tool listings to OpenAI-style function definitions."""
    definitions = []
    for tool in mcp_tools:
        if tool.name not in allowed:
            continue
        schema = json.loads(json.dumps(tool.input_schema))
        schema.pop("title", None)
        properties = schema.setdefault("properties", {})
        if tool.name == "export_build":
            schema["properties"] = {}
            schema.pop("required", None)
        if tool.name == "load_build":
            properties.pop("name", None)
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (tool.description or "")[:MAX_DESCRIPTION],
                    "parameters": schema,
                },
            }
        )
    return definitions


# --- MCP plumbing -------------------------------------------------------------------


class _LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        thread = threading.Thread(target=self.loop.run_forever, name="pob-mcp-loop", daemon=True)
        thread.start()

    def run(self, coro: Any, timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str
    data: Any = None  # parsed JSON when the tool returned JSON


class _Server:
    """One pob-mcp process with an open MCP session, owned by a task on the loop."""

    def __init__(self, runner: _LoopThread, command: list[str], env: dict[str, str]) -> None:
        self.runner = runner
        self.command = command
        self.env = env
        self.broken = False
        # Which build the process holds, so a follow-up with the same build can skip
        # reloading it: the source it was loaded from (or the share code it was last
        # exported as), and whether anything changed it since. "" = unknown.
        self.build_source = ""
        self.changed = True
        self.has_build = False  # False: the empty build a reset leaves behind
        self.tools: list[Any] = []
        self._requests: asyncio.Queue[Any] | None = None

    def start(self, timeout: float) -> None:
        self.tools = self.runner.run(self._start(), timeout)

    async def _start(self) -> list[Any]:
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[list[Any]] = loop.create_future()
        self._requests = asyncio.Queue()
        self._task = loop.create_task(self._serve(ready))
        return await ready

    async def _serve(self, ready: asyncio.Future[list[Any]]) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        assert self._requests is not None
        params = StdioServerParameters(command=self.command[0], args=self.command[1:], env=self.env)
        errlog = sys.stderr if settings.POB_DEBUG else open(os.devnull, "w")  # noqa: SIM115
        pending: Any = None
        try:
            async with (
                stdio_client(params, errlog=errlog) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                ready.set_result((await session.list_tools()).tools)
                while True:
                    pending = await self._requests.get()
                    if pending is None:
                        return
                    name, arguments, future, timeout = pending
                    try:
                        result = await session.call_tool(
                            name, arguments, read_timeout_seconds=timeout
                        )
                        if not future.done():
                            future.set_result(result)
                    except Exception as exc:  # timeout or protocol error
                        if not future.done():
                            timed_out = "timed out" in str(exc).lower()
                            future.set_exception(TimeoutError() if timed_out else exc)
                        raise  # the session may be stuck: stop this server
                    pending = None
        except BaseException as exc:
            self.broken = True
            if not ready.done():
                ready.set_exception(exc)
            if pending and not pending[2].done():
                pending[2].set_exception(PobUnavailable("Path of Building stopped unexpectedly."))
            if not isinstance(exc, Exception):
                raise
            logger.warning("pob-mcp server stopped: %s", exc)

    async def _call(self, name: str, arguments: dict[str, Any], timeout: float) -> Any:
        assert self._requests is not None
        future = asyncio.get_running_loop().create_future()
        await self._requests.put((name, arguments, future, timeout))
        return await future

    def call(self, name: str, arguments: dict[str, Any], timeout: float) -> ToolResult:
        if self.broken:
            raise PobUnavailable("Path of Building stopped unexpectedly.")
        try:
            result = self.runner.run(self._call(name, arguments, timeout), timeout + 5)
        except TimeoutError as exc:
            self.broken = True  # it may still be busy; don't hand it to anyone else
            raise PobToolError(f"{name} took longer than {timeout:.0f} seconds.") from exc
        except PobUnavailable:
            raise
        except Exception as exc:
            self.broken = True
            raise PobUnavailable(f"Path of Building failed: {exc}") from exc
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        return ToolResult(ok=not result.is_error, text=text, data=data)

    def close(self) -> None:
        if self._requests is not None and not self.broken:
            with suppress(Exception):  # best effort at shutdown
                self.runner.run(self._requests.put(None), 5)


class PobToolbox:
    """What the RAG loop sees: tool definitions and a safe `call`."""

    def __init__(
        self,
        server: _Server,
        definitions: list[dict[str, Any]],
        timeout: float,
        reused: bool = False,
    ) -> None:
        self._server = server
        self.definitions = definitions
        self._allowed = {d["function"]["name"] for d in definitions}
        self._timeout = timeout
        # True when the build asked for was already loaded and unchanged.
        self.reused = reused

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self._allowed:
            raise PobToolError(f"Unknown tool {name!r}.")
        if not self._server.has_build and name not in NO_BUILD_NEEDED:
            raise PobToolError(NO_BUILD_ERROR)
        if name not in READ_ONLY_TOOLS:
            self._server.changed = True
        result = self._server.call(name, sanitize_arguments(name, arguments), self._timeout)
        if name in ("new_build", "load_build") and result.ok:
            self._server.has_build = True
        if name == "export_build" and result.ok and isinstance(result.data, dict):
            code = result.data.get("code")
            if isinstance(code, str) and code:
                # The process now holds exactly this code; a follow-up sending it
                # back (the app attaches a changed build) needn't load it again.
                self._server.build_source, self._server.changed = code, False
        return result

    @property
    def has_build(self) -> bool:
        return self._server.has_build

    def call_internal(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """A call made by the app's own code (not chosen by the model), e.g. for a
        composite tool. It skips the allowlist but still tracks changes."""
        if name not in READ_ONLY_TOOLS:
            self._server.changed = True
        result = self._server.call(name, arguments, self._timeout)
        if name in ("new_build", "load_build") and result.ok:
            self._server.has_build = True
        return result

    def mark_loaded(self, source: str) -> None:
        """The build from `source` was just loaded and nothing has changed it yet."""
        self._server.build_source, self._server.changed = source, False
        self._server.has_build = True


class PobPool:
    def __init__(
        self,
        command: list[str],
        env: dict[str, str],
        size: int = 1,
        allowed: tuple[str, ...] = DEFAULT_TOOLS,
        call_timeout: float = 90.0,
        startup_timeout: float = 60.0,
    ) -> None:
        self.command = command
        self.env = env
        self.size = max(1, size)
        self.allowed = set(allowed)
        self.call_timeout = call_timeout
        self.startup_timeout = startup_timeout
        self._runner = _LoopThread()
        self._idle: queue.LifoQueue[_Server] = queue.LifoQueue()
        self._lock = threading.Lock()
        self._count = 0
        atexit.register(self.close)

    def _new_server(self) -> _Server:
        server = _Server(self._runner, self.command, self.env)
        started = time.monotonic()
        try:
            server.start(self.startup_timeout)
        except Exception as exc:
            raise PobUnavailable(f"Path of Building could not start: {exc}") from exc
        logger.info("Started pob-mcp in %.1fs", time.monotonic() - started)
        return server

    def _acquire(self, wait: float) -> _Server:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            create = self._count < self.size
            if create:
                self._count += 1
        if create:
            try:
                return self._new_server()
            except Exception:
                with self._lock:
                    self._count -= 1
                raise
        try:
            return self._idle.get(timeout=wait)
        except queue.Empty as exc:
            raise PobUnavailable("Path of Building is busy with other questions.") from exc

    def _release(self, server: _Server) -> None:
        if server.broken:
            server.close()
            with self._lock:
                self._count -= 1
        else:
            self._idle.put(server)

    @contextmanager
    def toolbox(self, wait: float = 60.0, build: str = "") -> Iterator[PobToolbox]:
        """Check out a Path of Building process.

        Every question starts from a clean state: the build it attached, or an empty
        build. When the process already holds that build unchanged (a follow-up about
        the same build), it's kept as it is instead of being reset and loaded again.
        """
        server = self._acquire(wait)
        try:
            reused = bool(build) and server.build_source == build and not server.changed
            if not reused and (server.build_source or server.changed):
                server.call("new_build", {}, self.call_timeout)
                server.build_source, server.changed, server.has_build = "", False, False
            definitions = openai_tool_definitions(server.tools, self.allowed)
            yield PobToolbox(server, definitions, self.call_timeout, reused=reused)
        finally:
            self._release(server)

    def close(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return


@lru_cache(maxsize=1)
def get_pool() -> PobPool | None:
    """The process-wide pool, or None when Path of Building isn't configured."""
    if not settings.POB_ENABLED:
        return None
    env = {**os.environ, "POB_PATH": settings.POB_PATH, "POB_MCP_GUIDE": "0"}
    return PobPool(
        command=[sys.executable, "-m", "pob_mcp", "--log-level", "WARNING"],
        env=env,
        size=settings.POB_POOL_SIZE,
        allowed=tuple(settings.POB_TOOLS) or DEFAULT_TOOLS,
        call_timeout=settings.POB_TOOL_TIMEOUT,
    )
