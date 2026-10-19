#!/usr/bin/env bash
#
# run_v3d_monitor.sh - run the V3D perf-counter sampler until it is stopped (SIGTERM).
#
# Uses V3D_DEV, V3D_INTERVAL_MS and V3D_COUNTERS ("all" or "51,55,66,...").
# Build the binary first with `make build/v3d_perfmon_monitor` in the project root.
# Output goes to stdout; the caller redirects it to a file.
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BIN="$BIN_DIR/v3d_perfmon_monitor"
[[ -x "$BIN" ]] || { echo "missing $BIN - run 'make' in $ROOT_DIR" >&2; exit 1; }

exec "$BIN" -d "$V3D_DEV" -i "$V3D_INTERVAL_MS" -c "$V3D_COUNTERS"
