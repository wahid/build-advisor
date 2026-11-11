import pytest

from advisor import warmup


@pytest.mark.parametrize(
    ("argv", "run_main", "expected"),
    [
        (["manage.py", "runserver", "0.0.0.0:8000"], "true", True),
        (["manage.py", "runserver"], None, False),  # the autoreloader's parent process
        (["/opt/venv/bin/gunicorn", "config.wsgi:application"], None, True),
        (["manage.py", "migrate"], None, False),
        (["celery", "-A", "config", "worker"], None, False),
    ],
)
def test_only_web_servers_warm_up(monkeypatch, argv, run_main, expected) -> None:
    monkeypatch.setattr("sys.argv", argv)
    if run_main:
        monkeypatch.setenv("RUN_MAIN", run_main)
    else:
        monkeypatch.delenv("RUN_MAIN", raising=False)

    assert warmup.is_web_server() is expected


def test_warm_up_loads_the_model_and_a_pob_process(mocker) -> None:
    embedder = mocker.Mock()
    mocker.patch("wiki.embeddings.get_embedder", return_value=embedder)
    pool = mocker.MagicMock()
    mocker.patch("advisor.pob.get_pool", return_value=pool)

    warmup.warm_up()

    embedder.embed_query.assert_called_once()
    pool.toolbox.assert_called_once()
