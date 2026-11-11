#!/bin/sh
# Smoke test for the production image (used by .github/workflows/docker.yml):
#   docker run --rm -e DJANGO_SECRET_KEY=... build-advisor:ci sh scripts/smoke_test.sh
set -e
python manage.py check
python -c 'import torch, sentence_transformers, pob_mcp; print("torch", torch.__version__)'
test -d "$POB_PATH/src"
cat "$POB_PATH/VERSION"
test -f /app/staticfiles/index.html
echo "frontend built"
echo "smoke test passed"
