#!/usr/bin/env bash
# hybrid/Storage/storage_stress.sh
# Targets: BCM2712 eMMC2/SD Host Controller & Descriptor DMA.
# Tool: fio with direct I/O and asynchronous libaio queues.

DURATION="${1:-30}"
SIZE="${2:-128M}"
TEST_FILE="/tmp/storage_stress.tmp"

echo "[Storage] Starting eMMC/SD storage DMA stressor for ${DURATION}s..."

if command -v fio >/dev/null 2>&1; then
    exec fio --name=storage_dma_stress \
             --filename="$TEST_FILE" \
             --size="$SIZE" \
             --readwrite=randrw \
             --rwmixread=70 \
             --bs=64k \
             --direct=1 \
             --numjobs=2 \
             --time_based \
             --runtime="$DURATION" \
             --ioengine=sync \
             --group_reporting \
             --unlink=1
else
    # Fallback to dd direct I/O loop
    END_TIME=$((SECONDS + DURATION))
    while (( SECONDS < END_TIME )); do
        dd if=/dev/urandom of="$TEST_FILE" bs=1M count=32 conv=fdatasync status=none 2>/dev/null
        dd if="$TEST_FILE" of=/dev/null bs=1M count=32 status=none 2>/dev/null
    done
    rm -f "$TEST_FILE"
fi
