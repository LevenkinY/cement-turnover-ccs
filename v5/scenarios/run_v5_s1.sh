#!/usr/bin/env bash
# v5 single-scenario runner. Run from the repository root.
set -euo pipefail
cd "$(dirname "$0")/../.."
RUN_NAME="${1:-p0_s1_$(date +%Y%m%d)}"
OUT="v5/results/${RUN_NAME}"
mkdir -p "${OUT}"
echo "[v5] output -> ${OUT}"
PYTHONPATH=v5/model .venv/bin/python -m src_v5.main \
  -s S1_baseline \
  --demand-scenario d_medium \
  --budget-case B40 \
  -o "${OUT}" \
  --solver-profile final \
  --mip-gap 0.005 \
  --threads 0 \
  2>&1 | tee "${OUT}/run.log"
