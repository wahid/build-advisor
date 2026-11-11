#!/bin/sh
# Diagnose GPU access inside a container: docker compose exec worker sh scripts/gpu_check.sh
echo "== nvidia-smi"; nvidia-smi --query-gpu=name,driver_version --format=csv 2>&1 | tail -1
echo "== NVIDIA env"; env | grep -E '^NVIDIA_' || echo "(none)"
echo "== WSL driver libs"; ls /usr/lib/wsl/lib 2>&1 | tr '\n' ' '; echo
echo "== libcuda on loader path"; ldconfig -p | grep -E 'libcuda\.so|libnvidia-ml' || echo "(none)"
echo "== libcuda inside the venv"; find /opt/venv -name 'libcuda.so*' 2>/dev/null || true
echo "== torch"
python - <<'PY'
import importlib.metadata as md
import torch

print("torch", torch.__version__, "built for CUDA", torch.version.cuda)
print("nvidia packages:", sorted(d.metadata["Name"] for d in md.distributions() if d.metadata["Name"].lower().startswith(("nvidia", "cuda"))))
try:
    print("cuda available:", torch.cuda.is_available())
    print("device:", torch.cuda.get_device_name(0))
except Exception as exc:
    print("CUDA ERROR:", exc)
PY
