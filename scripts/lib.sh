#!/usr/bin/env bash
# lib.sh - shared defaults and helpers. Source this file; do not execute it.
#
# Every setting can be overridden from the environment, e.g.
#   GPU_CMD="./build/gpu_task --size 1024" V3D_INTERVAL_MS=500 ./monitor_interference.sh

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$LIB_DIR/.." && pwd)"
SCRIPTS_DIR="$LIB_DIR"
BIN_DIR="$ROOT_DIR/build"          # C tools are built here by the Makefile

# ---- where results go / what to run -----------------------------------------
: "${DATA_DIR:=$ROOT_DIR/data}"      # results go to <project>/data/<name>/
: "${GPU_CMD:=./build/gpu_task}"
: "${GPU_TIMEOUT:=900}"                 # seconds, per gpu_task run
: "${GPU_CPUS:=}"                       # taskset list for gpu_task, e.g. "0"
: "${STRESS_CPUS:=}"                    # taskset list for the stressor, e.g. "1-3"

# ---- DVFS profiler -----------------------------------------------------------
: "${DVFS_SCRIPT:=}"                    # path to rpi5-dvfs-monitor.sh (auto-detected if empty)
: "${DVFS_INTERVAL:=0.5}"

# ---- V3D counter monitor -----------------------------------------------------
: "${V3D_DEV:=/dev/dri/renderD128}"
: "${V3D_INTERVAL_MS:=1000}"
: "${V3D_COUNTERS:=all}"                # "all" or "51,55,66,..."

# ---- sysbench / stress-ng ----------------------------------------------------
NT="${SB_THREADS:-$(nproc 2>/dev/null || echo 4)}"   # default thread count
: "${SB_REPORT:=1}"                     # --report-interval seconds
: "${SB_MAX_TIME:=3600}"                # safety cap; stressor is killed when gpu_task ends
: "${CPU_PRIME:=20000}"

# ---- orchestration timing ----------------------------------------------------
: "${WARMUP:=3}"                        # seconds of stress+monitors before gpu_task
: "${COOLDOWN:=3}"                      # seconds after gpu_task before stopping everything
: "${DROP_CACHES:=1}"                   # drop page cache before each run (root only)
SETTLE_TEMP="${SETTLE_TEMP-70}"         # wait until SoC <= this C before each run; empty = no wait
: "${SETTLE_MAX:=60}"                    # never wait longer than this many seconds

export DATA_DIR GPU_CMD GPU_TIMEOUT GPU_CPUS STRESS_CPUS DVFS_SCRIPT DVFS_INTERVAL \
       V3D_DEV V3D_INTERVAL_MS V3D_COUNTERS NT SB_REPORT SB_MAX_TIME CPU_PRIME \
       WARMUP COOLDOWN DROP_CACHES SETTLE_TEMP SETTLE_MAX

# Convert 32k / 4m / 1g (or plain bytes) to bytes.
to_bytes() {
    local n="${1%[kKmMgG]}" u="${1: -1}"
    case "${u,,}" in
        k) echo $((n * 1024)) ;;
        m) echo $((n * 1048576)) ;;
        g) echo $((n * 1073741824)) ;;
        *) echo "$n" ;;
    esac
}

# SoC temperature in C (empty if vcgencmd is unavailable).
soc_temp() {
    command -v vcgencmd >/dev/null 2>&1 || { echo ""; return 0; }
    vcgencmd measure_temp 2>/dev/null | sed -E 's/[^0-9.]//g'
}

# Wait (at most SETTLE_MAX seconds) until the SoC is at or below SETTLE_TEMP.
wait_settle() {
    [[ -n "$SETTLE_TEMP" ]] || return 0
    local waited=0 t
    while (( waited < SETTLE_MAX )); do
        t="$(soc_temp)"; [[ -n "$t" ]] || return 0
        awk -v t="$t" -v m="$SETTLE_TEMP" 'BEGIN{exit !(t<=m)}' && return 0
        echo "    [settle] SoC ${t}C > ${SETTLE_TEMP}C, waiting (${waited}s/${SETTLE_MAX}s)..."
        sleep 5; waited=$((waited + 5))
    done
    echo "    [settle] gave up after ${SETTLE_MAX}s, continuing"
}

# Locate the DVFS profiler script; prints absolute path or returns 1.
find_dvfs_script() {
    local c
    for c in "$DVFS_SCRIPT" "$SCRIPTS_DIR/rpi5-dvfs-monitor.sh" \
             "$ROOT_DIR/rpi5-dvfs-monitor.sh" "./rpi5-dvfs-monitor.sh"; do
        if [[ -n "$c" && -f "$c" ]]; then readlink -f "$c"; return 0; fi
    done
    return 1
}