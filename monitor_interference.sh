#!/usr/bin/env bash
#
# monitor_interference.sh - orchestrator.
#
# For every experiment it launches these separate programs/scripts:
#   scripts/run_dvfs.sh         DVFS / thermal profiler          -> dvfs.txt (+ rpi5-dvfs-logs/)
#   scripts/run_v3d_monitor.sh  V3D perf counters (bin/ from C)  -> v3d_counters.txt
#   scripts/run_stress.sh       sysbench / stress-ng             -> sysbench.txt
#   scripts/run_gpu_task.sh     ./build/gpu_task                 -> gpu_task.txt
#   scripts/write_meta.sh       command lines, timings, temps    -> meta.txt
# Experiments are defined in scripts/experiments.sh; shared settings are in scripts/lib.sh.
#
# Results: $DATA_DIR/<name>/   (DATA_DIR defaults to <project>/data; e.g. data/4mr, data/8mw)
#
# usage: ./monitor_interference.sh [options]
#   -l          list experiments and exit
#   -n          dry run (print what would run)
#   -f REGEX    only experiments whose folder name matches REGEX
#   -c CATS     only these categories (comma separated), e.g. dram_stream,pagefault
#   -F          re-run even if <name>/DONE exists
#   -h          help
#
# Run it from the directory that contains build/gpu_task (or set GPU_CMD).
# Typical: sudo ./monitor_interference.sh -f '^(4mr|8mw)$'
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$ROOT/scripts/lib.sh"

OPT_LIST=0; OPT_DRY=0; OPT_FORCE=0
EXP_ARGS=()

usage() { sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while getopts "lnf:c:Fh" o; do
    case "$o" in
        l) OPT_LIST=1 ;;
        n) OPT_DRY=1 ;;
        f) EXP_ARGS+=(-f "$OPTARG") ;;
        c) EXP_ARGS+=(-c "$OPTARG") ;;
        F) OPT_FORCE=1 ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

if (( OPT_LIST )); then
    exec bash "$SCRIPTS_DIR/experiments.sh" -l ${EXP_ARGS[@]+"${EXP_ARGS[@]}"}
fi

mapfile -t SELECTED < <(bash "$SCRIPTS_DIR/experiments.sh" ${EXP_ARGS[@]+"${EXP_ARGS[@]}"})

# ---- preflight ---------------------------------------------------------------
if (( ! OPT_DRY )); then
    for t in sysbench vcgencmd make gcc setsid timeout; do
        command -v "$t" >/dev/null 2>&1 || { echo "ERROR: '$t' not found" >&2; exit 1; }
    done
    read -ra _g <<<"$GPU_CMD"
    [[ -x "${_g[0]}" ]] || { echo "ERROR: gpu task '${_g[0]}' not found/executable (set GPU_CMD)" >&2; exit 1; }
    _g[0]="$(readlink -f "${_g[0]}")"
    GPU_CMD="${_g[*]}"
    export GPU_CMD
    find_dvfs_script >/dev/null || { echo "ERROR: rpi5-dvfs-monitor.sh not found (put it in scripts/ or set DVFS_SCRIPT)" >&2; exit 1; }
    [[ -e "$V3D_DEV" ]] || { echo "ERROR: $V3D_DEV does not exist" >&2; exit 1; }
    mkdir -p "$DATA_DIR" 2>/dev/null && [[ -w "$DATA_DIR" ]] || { echo "ERROR: cannot write $DATA_DIR (use sudo or chown)" >&2; exit 1; }
    make -s -C "$ROOT" build/v3d_perfmon_monitor || { echo "ERROR: make build/v3d_perfmon_monitor failed (need drm/v3d_drm.h, e.g. libdrm-dev)" >&2; exit 1; }
fi

# ---- process control ---------------------------------------------------------
DVFS_PID=""; V3D_PID=""; STRESS_PID=""

start_bg() {  # varname outfile cmd...
    local __var="$1" f="$2"; shift 2
    setsid "$@" >"$f" 2>&1 </dev/null &
    printf -v "$__var" '%s' "$!"
}

stop_group() {
    local pid="${1:-}"; [[ -n "$pid" ]] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || return 0
    local i
    for i in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -0 "$pid" 2>/dev/null && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; }
    wait "$pid" 2>/dev/null
}

stop_all() {
    stop_group "$STRESS_PID"; STRESS_PID=""
    stop_group "$V3D_PID";    V3D_PID=""
    stop_group "$DVFS_PID";   DVFS_PID=""
}

trap 'echo; echo "Interrupted - stopping background jobs..."; stop_all; exit 130' INT TERM

# ---- one experiment ----------------------------------------------------------
run_experiment() {
    local spec="$1" name cat mode
    IFS='|' read -r name cat mode _ <<<"$spec"
    local out="$DATA_DIR/$name" rc

    bash "$SCRIPTS_DIR/run_stress.sh" --check "$spec"; rc=$?
    case "$rc" in
        0|10) ;;
        11) echo "[skip] $name: stress-ng not installed"; return 0 ;;
        12) echo "[skip] $name: not enough free RAM"; return 0 ;;
        *)  echo "[skip] $name: run_stress.sh --check failed ($rc)"; return 0 ;;
    esac

    if (( ! OPT_FORCE )) && [[ -e "$out/DONE" ]]; then
        echo "[skip] $name: already done (-F to redo)"; return 0
    fi

    echo "=== $name  [$cat] ==="
    echo "    stress: $(bash "$SCRIPTS_DIR/run_stress.sh" --print "$spec")"
    (( OPT_DRY )) && return 0

    rm -rf "$out"; mkdir -p "$out" || { echo "cannot create $out"; return 1; }
    if [[ "$DROP_CACHES" == 1 && $EUID -eq 0 ]]; then sync; echo 3 > /proc/sys/vm/drop_caches; fi
    wait_settle
    local temp_before; temp_before="$(soc_temp)"

    # 1) monitors
    echo "    [start] DVFS profiler + V3D counter monitor"
    start_bg DVFS_PID "$out/dvfs.txt"          bash "$SCRIPTS_DIR/run_dvfs.sh" "$out"
    start_bg V3D_PID  "$out/v3d_counters.txt"  bash "$SCRIPTS_DIR/run_v3d_monitor.sh"

    # 2) interference (skipped for baseline)
    local t_stress=""
    if (( rc == 0 )); then
        t_stress="$(date +%s.%N)"
        start_bg STRESS_PID "$out/sysbench.txt" bash "$SCRIPTS_DIR/run_stress.sh" "$spec"
    else
        echo "(baseline: no interference)" > "$out/sysbench.txt"
    fi

    echo "    [warmup] ${WARMUP}s with stressor running"
    sleep "$WARMUP"

    # 3) GPU workload (foreground)
    local t_gpu0 t_gpu1 gpu_rc
    t_gpu0="$(date +%s.%N)"
    echo "    [gpu] running gpu_task (timeout ${GPU_TIMEOUT}s, output -> $out/gpu_task.txt)"
    bash "$SCRIPTS_DIR/run_gpu_task.sh" > "$out/gpu_task.txt" 2>&1
    gpu_rc=$?
    t_gpu1="$(date +%s.%N)"

    echo "    [stop] gpu_task exited (rc=$gpu_rc); cooldown ${COOLDOWN}s, then stopping stressor and monitors"
    sleep "$COOLDOWN"
    stop_all

    bash "$SCRIPTS_DIR/write_meta.sh" "$out" "$spec" "$gpu_rc" "$t_stress" "$t_gpu0" "$t_gpu1" "$temp_before"
    touch "$out/DONE"
    printf '    done: gpu_task rc=%s wall=%ss\n' "$gpu_rc" \
        "$(awk -v a="$t_gpu0" -v b="$t_gpu1" 'BEGIN{printf "%.2f", b-a}')"
}

# ---- main --------------------------------------------------------------------
echo "Experiments selected: ${#SELECTED[@]}  (data dir: $DATA_DIR, default threads: $NT)"
i=0
for spec in "${SELECTED[@]}"; do
    i=$((i + 1))
    printf '\n[%d/%d] ' "$i" "${#SELECTED[@]}"
    run_experiment "$spec"
done
echo
echo "All done. Results in $DATA_DIR/<name>/"