"""Error tracking is opt-in and never sends visitors' questions."""

import importlib

import config.settings as settings_module


def test_sentry_is_off_without_a_dsn(monkeypatch, mocker) -> None:
    init = mocker.patch("sentry_sdk.init")
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    importlib.reload(settings_module)

    init.assert_not_called()


def test_sentry_sends_no_personal_data_or_request_bodies(monkeypatch, mocker) -> None:
    init = mocker.patch("sentry_sdk.init")
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")

    importlib.reload(settings_module)

    kwargs = init.call_args.kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["max_request_body_size"] == "never"
    monkeypatch.delenv("SENTRY_DSN")
    importlib.reload(settings_module)
