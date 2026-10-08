#!/usr/bin/env bash
# Run inside the container: docker compose run --rm --entrypoint bash transcriber scripts/bringup.sh /archive/clips/pilot.mp4
set -euo pipefail
CLIP="${1:?path to a 30s+ clip under /archive}"
python - <<'EOF'
import torch, ctranslate2
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
print("device", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
print("ctranslate2", ctranslate2.__version__, "cuda devices", ctranslate2.get_cuda_device_count())
assert torch.cuda.is_available(), "CUDA not visible inside the container"
assert ctranslate2.get_cuda_device_count() > 0, "CTranslate2 cannot see the GPU: use the WhisperX fallback engine"
EOF
time python -m transcriber.cli --dry-run "$CLIP" --model large-v3 --device cuda
echo "BRING-UP OK"
