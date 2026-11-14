#!/usr/bin/env bash
# hybrid/CPU/cpu_stress.sh
# Targets: Cortex-A76 quad-core cluster & ARM DSU / L3 cache.
# Mode: Multi-threaded compute (matrix/prime) or cache thrashing.

DURATION="${1:-30}"
MODE="${2:-compute}" # "compute" or "cache"
THREADS="${3:-4}"

echo "[CPU] Starting CPU stressor: mode=$MODE threads=$THREADS duration=${DURATION}s"

if [[ "$MODE" == "cache" ]]; then
    if command -v stress-ng >/dev/null 2>&1; then
        exec stress-ng --cache "$THREADS" --cache-level 3 --timeout "${DURATION}s" --metrics-brief
    else
        exec sysbench memory --memory-block-size=2M --memory-total-size=1000G --threads="$THREADS" --time="$DURATION" run
    fi
else
    exec sysbench cpu --threads="$THREADS" --cpu-max-prime=50000 --time="$DURATION" run
fi
