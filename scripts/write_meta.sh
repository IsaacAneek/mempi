#!/usr/bin/env bash
#
# write_meta.sh - write <output_dir>/meta.txt describing one finished experiment.
#
# usage: write_meta.sh <output_dir> "<spec>" <gpu_rc> <stress_start> <gpu_start> <gpu_end> <temp_before>
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OUT_DIR="$1"; SPEC="$2"; GPU_RC="$3"; T_STRESS="$4"; T_GPU0="$5"; T_GPU1="$6"; TEMP_BEFORE="$7"
IFS='|' read -r NAME CAT MODE BLOCK OPER ACCESS THR SCOPE <<<"$SPEC"

{
    echo "name:            $NAME"
    echo "category:        $CAT"
    echo "mode:            $MODE"
    echo "block:           $BLOCK"
    echo "oper:            $OPER"
    echo "access:          $ACCESS"
    echo "threads:         $THR"
    echo "scope:           $SCOPE"
    echo "stress_cmd:      $(bash "$SCRIPTS_DIR/run_stress.sh" --print "$SPEC")"
    echo "gpu_cmd:         $GPU_CMD"
    echo "gpu_exit_code:   $GPU_RC   (124 = timed out)"
    echo "stress_start:    ${T_STRESS:-n/a}"
    echo "gpu_start:       $T_GPU0"
    echo "gpu_end:         $T_GPU1"
    echo "gpu_wall_s:      $(awk -v a="$T_GPU0" -v b="$T_GPU1" 'BEGIN{printf "%.3f", b-a}')"
    echo "warmup_s:        $WARMUP"
    echo "cooldown_s:      $COOLDOWN"
    echo "temp_before_c:   ${TEMP_BEFORE:-NA}"
    echo "temp_after_c:    $(soc_temp)"
    echo "v3d_interval_ms: $V3D_INTERVAL_MS"
    echo "v3d_counters:    $V3D_COUNTERS"
    echo "dvfs_interval_s: $DVFS_INTERVAL"
    echo "stress_cpus:     ${STRESS_CPUS:-all}"
    echo "gpu_cpus:        ${GPU_CPUS:-all}"
    echo "nproc:           $(nproc)"
    echo "kernel:          $(uname -r)"
    echo "sysbench:        $(sysbench --version 2>/dev/null)"
    echo "--- cpu / cache ---"
    lscpu 2>/dev/null | grep -iE 'model name|cache'
    echo "--- meminfo ---"
    grep -E 'MemTotal|MemAvailable' /proc/meminfo
} > "$OUT_DIR/meta.txt"
