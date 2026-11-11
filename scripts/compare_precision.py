"""Memory, speed and similarity of bge-m3 variants on the CPU, each in a fresh process.

docker compose exec -T worker python scripts/compare_precision.py
"""

import json
import os
import subprocess
import sys

QUESTIONS = [
    "Which support gems work with Righteous Fire on a Chieftain?",
    "What does freezing an enemy do?",
    "Can I place something on the ground that uses my spells for me?",
    "How does life leech work?",
    "Why do enemies take more damage after I hit them with lightning?",
]

CHILD = r"""
import json, resource, sys, time
import torch
from sentence_transformers import SentenceTransformer

def rss():
    with open("/proc/self/status") as fh:
        return int(next(x for x in fh if x.startswith("VmRSS")).split()[1]) / 1024

variant, questions = sys.argv[1], json.loads(sys.argv[2])
torch.set_num_threads(2)  # like a 2-vCPU server
base = rss()
t = time.monotonic()
model = SentenceTransformer("BAAI/bge-m3", device="cpu")
if variant == "int8":
    model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
load = time.monotonic() - t
import gc; gc.collect()
after = rss()
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
model.encode(["warm up"])
t = time.monotonic()
vecs = model.encode(questions, normalize_embeddings=True, batch_size=1)
per_q = (time.monotonic() - t) / len(questions)
for _ in range(20):  # many different words, so more of the vocabulary gets touched
    model.encode(questions * 4, normalize_embeddings=True)
used = rss()
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(json.dumps({"variant": variant, "base_mb": base, "model_mb": used - base, "peak_mb": peak,
                  "load_s": load, "ms_per_question": per_q * 1000, "vectors": vecs.tolist()}))
"""

results = {}
for variant in sys.argv[1:] or ("float32", "int8"):
    out = subprocess.run(
        [sys.executable, "-c", CHILD, variant, json.dumps(QUESTIONS)],
        capture_output=True,
        text=True,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    line = [x for x in out.stdout.splitlines() if x.startswith("{")]
    if not line:
        print(variant, "failed:", out.stderr[-1500:])
        continue
    r = json.loads(line[-1])
    results[variant] = r
    print(
        f"{variant}: process {r['base_mb']:.0f} MB before the model, +{r['model_mb']:.0f} MB "
        f"after use, peak {r['peak_mb']:.0f} MB, load {r['load_s']:.1f}s, "
        f"{r['ms_per_question']:.0f} ms/question"
    )

if len(results) == 2:
    import numpy as np

    a = np.array(results["float32"]["vectors"])
    b = np.array(results["int8"]["vectors"])
    print("cosine(int8, float32):", np.round((a * b).sum(axis=1), 4))
