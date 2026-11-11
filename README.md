# build-advisor

Ask questions about Path of Exile builds and get answers grounded in the
[Path of Exile wiki](https://www.poewiki.net), with links to the pages used.

> *"Which support gems work with Righteous Fire Chieftain?"*

Built with Django, PostgreSQL + pgvector, local `bge-m3` embeddings and an
LLM behind a provider-agnostic interface (DeepSeek by default).

## Status

| Phase | | Status |
|---|---|---|
| 1 | Collect wiki data (gems, uniques, ascendancies, mechanics) | ✅ done |
| 2 | Chunking + embeddings | ✅ done |
| 3 | RAG pipeline + React frontend with sources | ⏳ next |
| 4 | Tool calling with pob-mcp | |
| 5 | Evaluation set in CI | |
| 6 | Public demo on Railway | |

## Quick start (Docker)

```bash
cp .env.example .env          # set WIKI_USER_AGENT to include your contact address
docker compose up --build     # Django on http://localhost:8000, plus Celery, Postgres, Redis
```

In another terminal:

```bash
docker compose exec web python manage.py fetch_wiki --type gem --limit 20   # small trial run
docker compose exec web python manage.py fetch_wiki                         # everything (slow: one request per 2.5 s)
docker compose exec web python manage.py fetch_wiki --async                 # run in the Celery worker
docker compose exec web python manage.py createsuperuser                    # browse data at /admin/
```

Health check: `GET /api/health/`.

### Building the search index

```bash
docker compose exec worker python manage.py build_index --limit 50   # trial: embed 50 chunks
docker compose exec worker python manage.py build_index              # chunk + embed everything
docker compose exec web python manage.py build_index --async         # same, as a Celery task
```

The first run downloads `bge-m3` (~2 GB) into a Docker volume.

### Using an NVIDIA GPU

Embedding the whole wiki on CPU is slow. With an NVIDIA card (Docker Desktop on
Windows uses it through WSL2), start the stack with the GPU override:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

This builds PyTorch with CUDA and gives the Celery worker the GPU. The deployed
server stays on the CPU build: it only embeds the user's question, and the
document embeddings are already in the database.

## How data collection works

- **Page lists** come from the wiki's MediaWiki API: gems and uniques via
  Cargo queries on the `items` table, ascendancies and mechanics via categories.
- **Only changed pages are fetched.** Revision ids are checked in batches of 50;
  pages whose revision matches the stored `Source.revision_id` are skipped.
- **Polite to the wiki:** one request per 2.5 s by default (Cloudflare challenges faster clients), `maxlag=5`,
  backing off on `429`/`503` with `Retry-After`, and a descriptive User-Agent.
- **Raw pages are cached** in `data/raw/` per revision, so re-parsing never
  needs the network.
- **HTML → text** keeps section headings as `##` lines (for per-section
  chunking in phase 2) and drops navboxes, references and images.
- **Patch tracking:** each `Document` stores the game version it applies to,
  taken from the wiki's version table (latest released version) unless
  `POE_PATCH` is set.

## How indexing works

- **Chunks follow the wiki's sections**, not a fixed length. Long sections are
  split on paragraph boundaries (max `CHUNK_MAX_CHARS`, default 1500).
- Every chunk starts with `<page> — <section path>` so the embedding knows
  where it came from; reference and "see also" sections are dropped.
- Each `Chunk` carries type, patch, URL and section for filtering and citing.
- **Embeddings:** `BAAI/bge-m3` via sentence-transformers, normalised, stored
  in pgvector (1024 dimensions) with an HNSW index for cosine similarity.
- **Only changed text is re-embedded.** Documents are re-chunked only when
  their text hash changes, and chunks whose text is unchanged keep their
  embedding. Switching `EMBEDDING_MODEL` re-embeds everything.

## Development

```bash
uv sync                      # Python 3.12 (add --extra cpu or --extra cuda for embeddings)
uv run pytest                # tests (wiki and LLM calls are mocked)
uv run ruff check . && uv run ruff format .
```

Tests use `DATABASE_URL`; CI runs them against Postgres with pgvector.

## Data licence

Wiki content is from [poewiki.net](https://www.poewiki.net), under a Creative
Commons non-commercial licence ([CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/)). This project is non-commercial and links every answer back to
its source page. Path of Exile is a trademark of Grinding Gear Games.
