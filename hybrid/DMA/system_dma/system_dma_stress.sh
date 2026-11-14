#!/usr/bin/env bash
# hybrid/DMA/system_dma/system_dma_stress.sh
DURATION="${1:-30}"
SIZE_MB="${2:-16}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$DIR/system_dma_stress.py" --duration "$DURATION" --size-mb "$SIZE_MB"
