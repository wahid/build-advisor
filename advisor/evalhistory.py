"""A record of eval runs over time (evals/history.jsonl), for the How it works page.

Each line is one run: when, which commit, what was tried, and its headline scores.
`run_evals --record "label"` adds a line; experiments that weren't kept (a setting
tried and left off) are marked so the page can show them apart.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from django.conf import settings

HISTORY = Path(settings.BASE_DIR) / "evals" / "history.jsonl"
SCORES = ("cases", "hit@8", "recall@8", "mrr", "pass_rate", "grounded", "relevant")
MAX_ROWS = 60


def current_commit() -> str:
    """The short commit hash: $GIT_COMMIT, or git's, or "" (e.g. in the Docker image)."""
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"][:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=settings.BASE_DIR,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def entry(
    summary: dict[str, Any],
    label: str,
    config: str,
    when: date | None = None,
    commit: str | None = None,
    experiment: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "date": (when or date.today()).isoformat(),
        "commit": current_commit() if commit is None else commit,
        "label": label,
        "config": config,
        "experiment": experiment,
    }
    for key in SCORES:
        value = summary.get(key)
        row[key] = round(value, 3) if isinstance(value, float) else value
    return row


def append(row: dict[str, Any], path: Path = HISTORY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load(path: Path = HISTORY) -> list[dict[str, Any]]:
    """The runs, oldest first (the last MAX_ROWS)."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("date"):
            rows.append(row)
    return rows[-MAX_ROWS:]


def config_from_meta(meta: str) -> str:
    """'_2026-11-11, patch 3.29.3c, 2925 wiki pages, ..._' -> the settings part."""
    parts = [p.strip(" _.") for p in meta.split(",")]
    noise = r"^\d{4}-|^patch |^\d+\.\d+|\d+ (wiki pages|chunks)$|cases skipped$"
    keep = [p for p in parts if p and not re.search(noise, p)]
    return ", ".join(keep)
