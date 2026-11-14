#!/usr/bin/env bash
# hybrid/GPU/gpu_stress.sh
# Targets: VideoCore VII / V3D 7.1.10.2 GPU (12 QPU cores, TMU, L2T cache).
# Mode: Continuous compute shader execution and SSBO memory traffic.

DURATION="${1:-30}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GPU_BIN="$ROOT_DIR/build/gpu_task"

if [[ ! -x "$GPU_BIN" ]]; then
    make -s -C "$ROOT_DIR" build/gpu_task || { echo "Failed to build gpu_task"; exit 1; }
fi

echo "[GPU] Starting V3D GPU compute stressor for ${DURATION}s..."
END_TIME=$((SECONDS + DURATION))

count=0
while (( SECONDS < END_TIME )); do
    "$GPU_BIN" >/dev/null 2>&1
    count=$((count + 1))
done

echo "[GPU] Completed $count GPU task runs."
