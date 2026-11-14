#!/usr/bin/env bash
# hybrid/run_hybrid_benchmarks.sh
#
# Master Orchestrator for Multi-Engine Hybrid Contention Benchmarks on Raspberry Pi 5.
#
# For every hardware engine/interferer:
#   1. Starts DVFS / thermal profiler (dvfs.txt)
#   2. Starts V3D hardware counter profiler (v3d_counters.txt)
#   3. Launches the hardware engine stressor in the background
#   4. Executes the 64MB_rnd multi-threaded memory benchmark (sysbench.txt)
#   5. Executes the V3D GPU compute task (gpu_task.txt)
#   6. Collects metadata, latency degradation, and bus metrics (meta.txt)
#
# Output directory: hybrid/data/<engine_name>/

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HYBRID_DIR="$ROOT_DIR/hybrid"
DATA_DIR="$HYBRID_DIR/data"
SCRIPTS_DIR="$ROOT_DIR/scripts"

# Source project lib helpers
source "$SCRIPTS_DIR/lib.sh"

BENCH_TIME="${BENCH_TIME:-10}"       # Duration in seconds for sysbench 64MB_rnd test
WARMUP="${WARMUP:-2}"               # Warmup seconds before benchmark
COOLDOWN="${COOLDOWN:-2}"           # Cooldown seconds before teardown
OPT_FORCE=0
SELECTED_ENGINE=""
LIST_ONLY=0

ENGINES=(
    "baseline"
    "CPU"
    "GPU"
    "Storage"
    "Networking"
    "DMA/system_dma"
)

usage() {
    echo "Usage: $0 [options]"
    echo "  -l               List all available engines"
    echo "  -e <engine>      Run benchmark for a specific engine (e.g. GPU, ISP, DMA/dma0)"
    echo "  -t <seconds>     Benchmark run time per engine (default: 10s)"
    echo "  -f               Force re-run even if DONE marker exists"
    echo "  -h               Show this help message"
}

while getopts "le:t:fh" opt; do
    case "$opt" in
        l) LIST_ONLY=1 ;;
        e) SELECTED_ENGINE="$OPTARG" ;;
        t) BENCH_TIME="$OPTARG" ;;
        f) OPT_FORCE=1 ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

if (( LIST_ONLY )); then
    echo "Available Hardware Engines for Hybrid Contention Testing:"
    for eng in "${ENGINES[@]}"; do
        echo "  - $eng"
    done
    exit 0
fi

mkdir -p "$DATA_DIR"

# Background process management
DVFS_PID=""
V3D_PID=""
STRESS_PID=""

start_bg() {
    local __var="$1" f="$2"; shift 2
    setsid "$@" >"$f" 2>&1 </dev/null &
    printf -v "$__var" '%s' "$!"
}

stop_proc() {
    local pid="${1:-}"; [[ -n "$pid" ]] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || return 0
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$pid" 2>/dev/null && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; }
    wait "$pid" 2>/dev/null
}

stop_all() {
    stop_proc "$STRESS_PID"; STRESS_PID=""
    stop_proc "$V3D_PID";    V3D_PID=""
    stop_proc "$DVFS_PID";   DVFS_PID=""
}

trap 'echo; echo "Interrupted. Stopping background jobs..."; stop_all; exit 130' INT TERM

run_engine_experiment() {
    local engine="$1"
    local safe_name="${engine//\//_}"
    local out="$DATA_DIR/$safe_name"

    if (( ! OPT_FORCE )) && [[ -e "$out/DONE" ]]; then
        echo "[skip] $engine: already completed (-f to overwrite)"
        return 0
    fi

    echo "======================================================================"
    echo ">>> Running Hybrid Benchmark for Hardware Engine: $engine"
    echo "======================================================================"

    rm -rf "$out"
    mkdir -p "$out"

    local temp_before; temp_before="$(soc_temp)"
    local t_start t_end

    # 1. Start Monitors
    echo "    [1/5] Starting DVFS profiler and V3D hardware counter monitor..."
    start_bg DVFS_PID "$out/dvfs.txt" bash "$SCRIPTS_DIR/run_dvfs.sh" "$out"
    if [[ -x "$ROOT_DIR/build/v3d_perfmon_monitor" ]]; then
        start_bg V3D_PID "$out/v3d_counters.txt" bash "$SCRIPTS_DIR/run_v3d_monitor.sh"
    fi

    # 2. Launch Hardware Interferer
    local total_stress_time=$((WARMUP + BENCH_TIME + 15))
    if [[ "$engine" != "baseline" ]]; then
        local stress_script=""
        if [[ "$engine" == DMA/* ]]; then
            local sub="${engine#DMA/}"
            stress_script="$HYBRID_DIR/DMA/$sub/${sub}_stress.sh"
            if [[ ! -x "$stress_script" && -x "$HYBRID_DIR/DMA/$sub/${sub}_dma_stress.sh" ]]; then
                stress_script="$HYBRID_DIR/DMA/$sub/${sub}_dma_stress.sh"
            fi
        else
            stress_script="$HYBRID_DIR/$engine/${engine,,}_stress.sh"
        fi

        if [[ -x "$stress_script" ]]; then
            echo "    [2/5] Launching hardware engine stressor: $stress_script (${total_stress_time}s)..."
            start_bg STRESS_PID "$out/stressor_output.txt" bash "$stress_script" "$total_stress_time"
        else
            echo "    [2/5] WARNING: Stress script $stress_script not found or executable"
        fi
    else
        echo "    [2/5] Baseline run (no interferer running)"
        echo "baseline" > "$out/stressor_output.txt"
    fi

    echo "    [3/5] Warming up for ${WARMUP}s..."
    sleep "$WARMUP"

    # 3. Execute Victim Benchmark 1: 64MB_rnd Multithreaded Memory Stress Test
    echo "    [4/5] Executing 64MB_rnd sysbench memory benchmark (${BENCH_TIME}s)..."
    t_start="$(date +%s.%N)"
    sysbench memory \
        --memory-block-size=64M \
        --memory-total-size=100G \
        --memory-access-mode=rnd \
        --threads=4 \
        --time="$BENCH_TIME" \
        run > "$out/sysbench.txt" 2>&1
    t_end="$(date +%s.%N)"

    # 4. Execute Victim Benchmark 2: V3D Compute Task
    echo "    [5/5] Executing V3D GPU compute task..."
    local t_gpu0 t_gpu1 gpu_rc=0
    t_gpu0="$(date +%s.%N)"
    if [[ -x "$ROOT_DIR/build/gpu_task" ]]; then
        "$ROOT_DIR/build/gpu_task" > "$out/gpu_task.txt" 2>&1 || gpu_rc=$?
    fi
    t_gpu1="$(date +%s.%N)"

    sleep "$COOLDOWN"
    stop_all

    # 5. Extract Key Metrics and Record Metadata
    local temp_after; temp_after="$(soc_temp)"
    local throughput_mibs="0.0"
    local ops_sec="0.0"
    local avg_lat_ms="0.0"
    local p95_lat_ms="0.0"

    if [[ -f "$out/sysbench.txt" ]]; then
        throughput_mibs="$(grep -oE '[0-9.]+ MiB/sec' "$out/sysbench.txt" | awk '{print $1}' || echo '0.0')"
        ops_sec="$(grep -oE '\([0-9.]+ per second\)' "$out/sysbench.txt" | grep -oE '[0-9.]+' || echo '0.0')"
        avg_lat_ms="$(grep -E 'avg:' "$out/sysbench.txt" | awk '{print $2}' || echo '0.0')"
        p95_lat_ms="$(grep -E '95th percentile:' "$out/sysbench.txt" | awk '{print $3}' || echo '0.0')"
    fi

    local gpu_compute_ms="0.0"
    local gpu_e2e_ms="0.0"
    local gpu_resid_ms="0.0"
    if [[ -f "$out/gpu_task.txt" ]]; then
        gpu_e2e_ms="$(grep -E 'End-to-end latency:' "$out/gpu_task.txt" | awk '{print $3}' || echo '0.0')"
        gpu_compute_ms="$(grep -E 'GPU elapsed time:' "$out/gpu_task.txt" | awk '{print $4}' || echo '0.0')"
        gpu_resid_ms="$(grep -E 'E2E minus GPU elapsed:' "$out/gpu_task.txt" | awk '{print $5}' || echo '0.0')"
    fi

    {
        echo "engine:            $engine"
        echo "safe_name:         $safe_name"
        echo "bench_time_s:      $BENCH_TIME"
        echo "mem_throughput:    $throughput_mibs MiB/sec"
        echo "mem_ops_sec:       $ops_sec"
        echo "mem_avg_lat_ms:    $avg_lat_ms"
        echo "mem_p95_lat_ms:    $p95_lat_ms"
        echo "gpu_e2e_ms:        $gpu_e2e_ms"
        echo "gpu_compute_ms:    $gpu_compute_ms"
        echo "gpu_residual_ms:   $gpu_resid_ms"
        echo "temp_before_c:     $temp_before"
        echo "temp_after_c:      $temp_after"
        echo "timestamp:         $(date --iso-8601=seconds)"
    } > "$out/meta.txt"

    touch "$out/DONE"
    printf "    >>> Done: %s | 64MB_rnd: %s MiB/s, Lat: %s ms | GPU: %s ms (comp=%s ms, resid=%s ms)\n\n" \
        "$engine" "$throughput_mibs" "$avg_lat_ms" "$gpu_e2e_ms" "$gpu_compute_ms" "$gpu_resid_ms"
}

# Main Execution Flow
TARGET_ENGINES=()
if [[ -n "$SELECTED_ENGINE" ]]; then
    TARGET_ENGINES=("$SELECTED_ENGINE")
else
    TARGET_ENGINES=("${ENGINES[@]}")
fi

echo "======================================================================"
echo "Raspberry Pi 5 Hybrid Multi-Engine Contention Benchmark Suite"
echo "Engines to test: ${#TARGET_ENGINES[@]} (Duration per test: ${BENCH_TIME}s)"
echo "Output Directory: $DATA_DIR"
echo "======================================================================"

idx=1
for eng in "${TARGET_ENGINES[@]}"; do
    printf "[%2d/%2d] " "$idx" "${#TARGET_ENGINES[@]}"
    run_engine_experiment "$eng"
    idx=$((idx + 1))
done

# Generate Summary CSV
SUMMARY_CSV="$DATA_DIR/hybrid_benchmark_results.csv"
echo "engine,throughput_mibs,ops_sec,avg_lat_ms,p95_lat_ms,gpu_e2e_ms,gpu_compute_ms,gpu_residual_ms,temp_before_c,temp_after_c" > "$SUMMARY_CSV"

for eng in "${TARGET_ENGINES[@]}"; do
    safe_name="${eng//\//_}"
    d="$DATA_DIR/$safe_name"
    if [[ -f "$d/meta.txt" ]]; then
        tp="$(grep -E '^mem_throughput:' "$d/meta.txt" | awk '{print $2}')"
        ops="$(grep -E '^mem_ops_sec:' "$d/meta.txt" | awk '{print $2}')"
        avg_lat="$(grep -E '^mem_avg_lat_ms:' "$d/meta.txt" | awk '{print $2}')"
        p95_lat="$(grep -E '^mem_p95_lat_ms:' "$d/meta.txt" | awk '{print $2}')"
        g_e2e="$(grep -E '^gpu_e2e_ms:' "$d/meta.txt" | awk '{print $2}')"
        g_comp="$(grep -E '^gpu_compute_ms:' "$d/meta.txt" | awk '{print $2}')"
        g_res="$(grep -E '^gpu_residual_ms:' "$d/meta.txt" | awk '{print $2}')"
        t_bef="$(grep -E '^temp_before_c:' "$d/meta.txt" | awk '{print $2}')"
        t_aft="$(grep -E '^temp_after_c:' "$d/meta.txt" | awk '{print $2}')"
        echo "$eng,$tp,$ops,$avg_lat,$p95_lat,$g_e2e,$g_comp,$g_res,$t_bef,$t_aft" >> "$SUMMARY_CSV"
    fi
done

echo
echo "======================================================================"
echo "Hybrid Benchmarking Suite Completed Successfully!"
echo "Analysis Data Directory: $DATA_DIR"
echo "Summary Results CSV:     $SUMMARY_CSV"
echo "======================================================================"
