#!/usr/bin/env bash
#
# run_stress.sh - launch the interference workload for one experiment spec.
#
# usage:
#   run_stress.sh "<spec>"          run the stressor (exec's sysbench/stress-ng;
#                                   page-fault mode loops until killed)
#   run_stress.sh --print "<spec>"  print the command line only
#   run_stress.sh --check "<spec>"  exit code tells if the experiment can run:
#                                     0  ok
#                                     10 baseline (no stressor wanted)
#                                     11 required tool (stress-ng) missing
#                                     12 not enough free RAM
#
# spec = name|category|mode|block|oper|access|threads|scope   (see experiments.sh)
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ACTION=run
case "${1:-}" in
    --print) ACTION=print; shift ;;
    --check) ACTION=check; shift ;;
esac
SPEC="${1:?usage: run_stress.sh [--print|--check] \"<spec>\"}"
IFS='|' read -r NAME CAT MODE BLOCK OPER ACCESS THR SCOPE <<<"$SPEC"

CMD=(); LOOP=0

need_ng() { command -v stress-ng >/dev/null 2>&1; }

case "$MODE" in
    none)
        [[ "$ACTION" == check ]] && exit 10
        echo "(baseline: no interference)"; exit 0 ;;
    mem)
        CMD=(sysbench memory
            --memory-block-size="${BLOCK^^}" --memory-total-size=1000T
            --memory-oper="$OPER" --memory-access-mode="$ACCESS"
            --memory-scope="$SCOPE" --threads="$THR"
            --events=0 --time="$SB_MAX_TIME" --report-interval="$SB_REPORT" run) ;;
    cpu)
        CMD=(sysbench cpu --cpu-max-prime="$CPU_PRIME" --threads="$THR"
            --events=0 --time="$SB_MAX_TIME" --report-interval="$SB_REPORT" run) ;;
    mutex)
        CMD=(sysbench mutex --mutex-num="$BLOCK" --threads="$THR"
            --events=0 --time="$SB_MAX_TIME" --report-interval="$SB_REPORT" run) ;;
    threads)
        CMD=(sysbench threads --thread-yields=100 --thread-locks=8 --threads="$THR"
            --events=0 --time="$SB_MAX_TIME" --report-interval="$SB_REPORT" run) ;;
    pf)
        LOOP=1
        CMD=(sysbench memory
            --memory-block-size="${BLOCK^^}" --memory-total-size="${BLOCK^^}"
            --memory-oper="$OPER" --memory-access-mode="$ACCESS"
            --memory-scope="$SCOPE" --threads="$THR" --time=0 run) ;;
    ngfault)
        need_ng || { [[ "$ACTION" == check ]] && exit 11; echo "stress-ng missing" >&2; exit 1; }
        CMD=(stress-ng --fault "$THR" --timeout "${SB_MAX_TIME}s" --metrics-brief) ;;
    ngmmap)
        need_ng || { [[ "$ACTION" == check ]] && exit 11; echo "stress-ng missing" >&2; exit 1; }
        CMD=(stress-ng --mmap "$THR" --mmap-bytes "${BLOCK^^}"
            --timeout "${SB_MAX_TIME}s" --metrics-brief) ;;
    ngvm)
        need_ng || { [[ "$ACTION" == check ]] && exit 11; echo "stress-ng missing" >&2; exit 1; }
        # no --vm-keep: each pass unmaps and re-faults its pages
        CMD=(stress-ng --vm "$THR" --vm-bytes "${BLOCK^^}" --vm-method write64
            --timeout "${SB_MAX_TIME}s" --metrics-brief) ;;
    *)
        echo "unknown mode '$MODE' in spec: $SPEC" >&2; exit 1 ;;
esac

# Memory safety check (working set must fit in 70% of MemAvailable)
if [[ "$ACTION" == check ]]; then
    case "$MODE" in
        mem|pf|ngmmap|ngvm)
            need="$(to_bytes "$BLOCK")"
            [[ "$SCOPE" == global ]] || need=$((need * THR))
            avail_kb="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
            if (( need > avail_kb * 1024 * 7 / 10 )); then
                echo "needs $((need / 1048576)) MB, only $((avail_kb / 1024)) MB available" >&2
                exit 12
            fi ;;
    esac
    exit 0
fi

PREFIX=()
[[ -n "$STRESS_CPUS" ]] && PREFIX=(taskset -c "$STRESS_CPUS")
FULL=(${PREFIX[@]+"${PREFIX[@]}"} "${CMD[@]}")

if [[ "$ACTION" == print ]]; then
    printf '%q ' "${FULL[@]}"
    (( LOOP )) && printf '  # looped until stopped'
    echo
    exit 0
fi

if (( LOOP )); then
    while :; do "${FULL[@]}" || sleep 0.2; done
else
    exec "${FULL[@]}"
fi
