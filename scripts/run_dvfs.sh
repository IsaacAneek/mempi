#!/usr/bin/env bash
#
# run_dvfs.sh - run your rpi5-dvfs-monitor.sh until it is stopped (SIGTERM).
#
# usage: run_dvfs.sh <output_dir>
#
# The profiler writes its rpi5-dvfs-logs/<timestamp>/ folder into the current
# directory, so we cd into <output_dir> first; its live status lines go to
# stdout (the caller redirects them to dvfs.txt).
#
# The profiler is located via $DVFS_SCRIPT, scripts/rpi5-dvfs-monitor.sh,
# <project>/rpi5-dvfs-monitor.sh or ./rpi5-dvfs-monitor.sh.
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OUT_DIR="${1:?usage: run_dvfs.sh <output_dir>}"
DVFS="$(find_dvfs_script)" || { echo "rpi5-dvfs-monitor.sh not found (set DVFS_SCRIPT)" >&2; exit 1; }

cd "$OUT_DIR" || exit 1
exec bash "$DVFS" "$DVFS_INTERVAL" 0
