"""Time how long a question takes on the same path as the website:
docker compose exec -T worker python manage.py shell < scripts/time_question.py
"""

import time

from advisor.pob import get_pool
from advisor.rag import answer_stream
from wiki.embeddings import get_embedder

QUESTIONS = [
    "Which support gems work with Righteous Fire on a Chieftain?",
    "What does freezing an enemy do?",
]

# What the server's warm-up does at startup; not part of a visitor's wait.
get_embedder().embed_query("warm up")
pool = get_pool()
if pool:
    with pool.toolbox():
        pass

for question in QUESTIONS:
    t = time.monotonic()
    marks = {}
    for event in answer_stream(question):
        now = round(time.monotonic() - t, 1)
        if event["type"] == "rewrite":
            marks["searched for"] = f"{event['terms']!r} (tools: {event['tools']}) at {now}s"
        elif event["type"] == "sources":
            marks.setdefault("sources", f"{now}s")
        elif event["type"] == "delta":
            marks.setdefault("first word", f"{now}s")
    marks["complete"] = f"{time.monotonic() - t:.1f}s"
    print(question, "|", " | ".join(f"{k}: {v}" for k, v in marks.items()))
