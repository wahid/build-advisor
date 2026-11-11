from celery import shared_task

from .ingest import ingest


@shared_task(name="wiki.ingest")
def ingest_wiki(
    doc_types: list[str] | None = None, limit: int | None = None, refresh: bool = False
) -> dict[str, object]:
    return ingest(doc_types=doc_types, limit=limit, refresh=refresh).as_dict()
