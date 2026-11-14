#!/usr/bin/env bash
# hybrid/Networking/networking_stress.sh
DURATION="${1:-30}"
THREADS="${2:-4}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v iperf3 >/dev/null 2>&1; then
    echo "[Networking] Running iperf3 loopback stressor..."
    iperf3 -s -p 5201 -D 2>/dev/null
    iperf3 -c 127.0.0.1 -p 5201 -t "$DURATION" -P "$THREADS" >/dev/null 2>&1 &
    IPERF_PID=$!
    wait "$IPERF_PID" 2>/dev/null
    pkill -f "iperf3 -s" 2>/dev/null
else
    python3 "$DIR/networking_workload.py" --duration "$DURATION" --threads "$THREADS"
fi
