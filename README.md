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
| 3 | RAG pipeline + React frontend with sources | 🚧 API done, frontend next |
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

### Asking questions

Set `LLM_PROVIDER`, `LLM_MODEL` and `LLM_API_KEY` in `.env` (then
`docker compose up -d` to reload it), and:

```bash
docker compose exec worker python manage.py search "Cast when Damage Taken"   # retrieval only
docker compose exec worker python manage.py ask "Which support gems work with Righteous Fire Chieftain?"
```

Or over HTTP, streamed as Server-Sent Events (`sources`, then `delta`s, then `done`):

```bash
curl -N -X POST http://localhost:8000/api/ask/ -H "Content-Type: application/json" \
  -d '{"question": "How does ignite work?", "doc_types": ["mechanic"]}'
```

Add `"stream": false` for a single JSON response.

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
- **Optional proxies and parallel downloads:** list proxies in `proxies.txt`
  (one per line, see `proxies.example.txt`; http, https, socks4 and socks5) or
  in `WIKI_PROXIES`. Pages are then downloaded by `WIKI_WORKERS` threads
  (default 4, max 16), each with its own home proxy. When a proxy fails
  (connection error, timeout, `407`/`502`/`504`) the request moves to another
  proxy and the failed one is skipped for `WIKI_PROXY_COOLDOWN` seconds. Each
  worker still keeps its own request interval and backoff, and a Cloudflare
  challenge stops the whole run.
- **`fetch_wiki --direct`** skips the proxies and fetches pages one at a time
  over your own connection, throttled to `WIKI_REQUEST_INTERVAL` and backing
  off on `429`/`503`. Use it to retry pages that failed through proxies; only
  missing or changed pages are downloaded.
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

## How answering works

1. **Hybrid retrieval** (`wiki/search.py`) merges three ranked lists with
   reciprocal rank fusion: vector similarity, Postgres full-text search, and
   chunks of pages whose title appears in the question (one per page first,
   so "Righteous Fire Chieftain" finds both pages). Common words ("support",
   "gem") are ignored for keyword search, and at most 3 chunks per page are
   kept.
2. **Grounded prompt** (`advisor/prompts.py`): the top 8 chunks are numbered
   and the model is told to use only those, cite them as `[n]`, say when the
   sources don't cover the question, and mention the game version.
3. **Provider-independent LLM** (`advisor/llm.py`): DeepSeek, OpenAI and
   Anthropic through their OpenAI-compatible APIs, chosen by `LLM_PROVIDER`.
   Model names live only in configuration.
4. **Streaming** (`POST /api/ask/`): sources are sent first, then the answer
   token by token, then which sources were actually cited.

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
