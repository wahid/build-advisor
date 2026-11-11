from celery import shared_task

from .indexing import build_chunks, embed_pending
from .ingest import ingest


@shared_task(name="wiki.ingest")
def ingest_wiki(
    doc_types: list[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
    direct: bool = False,
) -> dict[str, object]:
    return ingest(doc_types=doc_types, limit=limit, refresh=refresh, direct=direct).as_dict()


@shared_task(name="wiki.build_index")
def build_index(force: bool = False, embed: bool = True) -> dict[str, object]:
    result: dict[str, object] = dict(build_chunks(force=force).as_dict())
    result["embedded"] = embed_pending() if embed else 0
    return result
