"""Progress from slow tools, so the app can show "12 of 40" while they run.

A slow tool is written as a generator that yields Progress now and then and
returns its result; `drain` runs one to the end for callers that only want the
result. (Generators rather than threads: the tools use the database and PoB's
event loop, which are simplest on one thread.)
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Progress:
    done: int
    total: int
    label: str = ""

    def event(self, call_id: str, name: str) -> dict[str, Any]:
        return {
            "type": "tool_progress",
            "id": call_id,
            "name": name,
            "done": self.done,
            "total": self.total,
            "label": self.label[:80],
        }


type Steps[T] = Generator[Progress, None, T]


def drain[T](steps: Steps[T]) -> T:
    """Run a progress generator to the end and return its result."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value
