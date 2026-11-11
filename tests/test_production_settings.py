"""Production settings are module-level, so they're checked in a fresh process."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOOD_KEY = "k" * 30 + "0123456789abcdefghijklmnopqrstuvwxyz"


def run_django(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": "sqlite:////tmp/settings-test.sqlite3", **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_https_mode_refuses_the_default_secret_key() -> None:
    result = run_django({"DJANGO_HTTPS": "true", "DJANGO_SECRET_KEY": ""}, "check")

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_https_mode_passes_the_deploy_checks() -> None:
    env = {
        "DJANGO_HTTPS": "true",
        "DJANGO_DEBUG": "false",
        "DJANGO_SECRET_KEY": GOOD_KEY,
        "DJANGO_ALLOWED_HOSTS": "advisor.example.com",
    }

    result = run_django(env, "check", "--deploy", "--fail-level", "WARNING")

    assert result.returncode == 0, result.stderr
