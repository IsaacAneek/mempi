#!/usr/bin/env bash
#
# run_gpu_task.sh - run the GPU workload once, in the foreground.
#
# Uses GPU_CMD (default ./build/gpu_task), GPU_TIMEOUT and optional GPU_CPUS
# (taskset list). The exit code is gpu_task's (124 = timed out).
# All output goes to stdout/stderr; the caller redirects it to a file.
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

read -ra GPU_ARR <<<"$GPU_CMD"
[[ -x "${GPU_ARR[0]}" ]] || { echo "gpu task not executable: ${GPU_ARR[0]}" >&2; exit 127; }

PREFIX=()
[[ -n "$GPU_CPUS" ]] && PREFIX=(taskset -c "$GPU_CPUS")

exec ${PREFIX[@]+"${PREFIX[@]}"} timeout "$GPU_TIMEOUT" "${GPU_ARR[@]}"
