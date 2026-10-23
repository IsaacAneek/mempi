#!/usr/bin/env bash
#
# experiments.sh - defines the interference experiment matrix.
#
# Prints one spec per line:  name|category|mode|block|oper|access|threads|scope
#
#   -l          pretty table instead of raw specs
#   -f REGEX    only experiments whose name matches REGEX
#   -c CATS     only these categories (comma separated)
#
# Folder naming (default = local scope, sequential access, nproc threads):
#   <block><op>[_rnd][_t<threads>][_g]
#     4mr    4 MB block, memory-oper=read       8mw   8 MB block, memory-oper=write
#     32kn   32 KB block, memory-oper=none (pure CPU loop)
#     _rnd   random access        _t8  8 threads        _g  --memory-scope=global
#
# Raspberry Pi 5 (Cortex-A76): L1D 64 KB/core, L2 512 KB/core, L3 2 MB shared
# (documented sizes; treat the category names below as hypotheses until confirmed
# with measurements: size sweeps, cache-miss counters, AXI/bus counters).
# With --memory-scope=local each thread owns one block, so the AGGREGATE working set
# is block * threads (4 threads by default):
#   16k..256k  4 x 64 KB .. 4 x 256 KB = 64 KB .. 1 MB   fits private L1/L2 + L3
#   1m         4 x 1 MB   = 4 MB   > 2 MB L3  -> cache pressure (per-thread block > half of L2)
#   2m,4m      4 x 2 MB .. 4 x 4 MB = 8-16 MB  -> spills the shared L3
#   8m..256m   32 MB .. 1 GB       -> large working set, sustained DRAM traffic expected
# With --memory-scope=global all threads share ONE block (aggregate = block).
#
set -uo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OPT_LIST=0; OPT_FILTER=""; OPT_CATS=""
while getopts "lf:c:" o; do
    case "$o" in
        l) OPT_LIST=1 ;;
        f) OPT_FILTER="$OPTARG" ;;
        c) OPT_CATS="$OPTARG" ;;
        *) exit 1 ;;
    esac
done

EXPS=()
declare -A SEEN=()

add() {  # name category mode block oper access threads scope
    [[ -n "${SEEN[$1]:-}" ]] && return
    SEEN[$1]=1
    EXPS+=("$1|$2|$3|$4|$5|$6|$7|$8")
}

mkname() {  # block oper access threads scope
    local b="${1,,}" o="$2" a="$3" t="$4" s="$5" n opl
    case "$o" in read) opl=r ;; write) opl=w ;; none) opl=n ;; *) opl=x ;; esac
    n="${b}${opl}"
    [[ "$a" == "rnd" ]]    && n+="_rnd"
    [[ "$t" != "$NT" ]]    && n+="_t${t}"
    [[ "$s" == "global" ]] && n+="_g"
    printf '%s' "$n"
}

gen_mem() {  # category blocks ops accesses threads scopes
    local cat="$1" blocks="$2" ops="$3" accs="$4" thr="$5" scopes="$6" b o a t s
    for b in $blocks; do for o in $ops; do for a in $accs; do
        for t in $thr; do for s in $scopes; do
            add "$(mkname "$b" "$o" "$a" "$t" "$s")" "$cat" mem "$b" "$o" "$a" "$t" "$s"
        done; done
    done; done; done
}

# 0. reference: GPU alone (monitors still running)
add baseline baseline none - - - - -

# 1. small working set (private buffers, aggregate <= 1 MB; expected to stay in L1/L2/L3)
gen_mem cache_resident "16k 32k 128k 256k" "read write" "seq rnd" "$NT" local

# 2. cache pressure: aggregate block*threads above the 2 MB L3 (1m = 4 MB, 2m = 8 MB, 4m = 16 MB)
gen_mem cache_evict "1m 2m 4m" "read write" "seq rnd" "$NT" local

# 3. DRAM streaming (prefetcher-friendly, max bandwidth)
gen_mem dram_stream "8m 16m 64m 256m" "read write" seq "$NT" local

# 4. DRAM random (prefetcher-hostile, row-miss heavy)
gen_mem dram_random "8m 16m 64m 256m" "read write" rnd "$NT" local

# 5. coherence / CPU-side contention: all threads share ONE buffer (scope=global)
gen_mem coherence "16k 64k 256k" write "seq rnd" "$NT" global
gen_mem coherence "32k" write seq "2 8" global
gen_mem coherence "256k 8m" read seq "$NT" global

# 6. thread-count sweep (bandwidth intensity knob)
gen_mem thread_sweep "4m 64m" "read write" seq "1 2 8" local

# 7. CPU-side only (no memory-bandwidth pressure)
gen_mem cpu_side "32k" none seq "$NT 8 16" local
for t in 1 2 "$NT" 8 16; do
    add "cpu_prime_t${t}" cpu_side cpu - - - "$t" -
done
for t in 2 "$NT" 8 16; do
    add "mutex1_t${t}"    cpu_side mutex 1    - - "$t" -    # one hot mutex: max contention
    add "mutex4096_t${t}" cpu_side mutex 4096 - - "$t" -
done
for t in "$NT" 16 64; do
    add "threads_t${t}"   cpu_side threads - - - "$t" -     # yield/lock scheduler storm
done

# 8. repeated page faults (not cache eviction / DRAM streaming): sysbench is
#    re-launched in a loop with total-size == block-size, so every pass mmaps and
#    first-touches fresh pages.
for b in 16m 64m 256m; do
    add "pf_${b}w_t${NT}" pagefault pf "$b" write seq "$NT" local
done
add "pf_64mw_t1"       pagefault pf 64m write seq 1 local
add "pf_64mr_t${NT}"   pagefault pf 64m read  seq "$NT" local
#    stress-ng page-fault stressors (skipped at run time if stress-ng is missing)
add "ng_fault_t${NT}"  pagefault ngfault -    - - "$NT" -
add "ng_mmap_t${NT}"   pagefault ngmmap  256m - - "$NT" -
add "ng_vm_t${NT}"     pagefault ngvm    256m - - "$NT" -

# ---- selection / output ------------------------------------------------------
count=0
(( OPT_LIST )) && printf '%-24s %-15s %-8s %-6s %-6s %-5s %-4s %-6s\n' \
    NAME CATEGORY MODE BLOCK OPER ACC THR SCOPE
for spec in "${EXPS[@]}"; do
    IFS='|' read -r name cat mode block oper access thr scope <<<"$spec"
    if [[ -n "$OPT_FILTER" ]] && ! [[ "$name" =~ $OPT_FILTER ]]; then continue; fi
    if [[ -n "$OPT_CATS" && ",${OPT_CATS}," != *",${cat},"* ]]; then continue; fi
    count=$((count + 1))
    if (( OPT_LIST )); then
        printf '%-24s %-15s %-8s %-6s %-6s %-5s %-4s %-6s\n' \
            "$name" "$cat" "$mode" "$block" "$oper" "$access" "$thr" "$scope"
    else
        echo "$spec"
    fi
done
(( OPT_LIST )) && printf '\n%d experiments selected (of %d)\n' "$count" "${#EXPS[@]}"
exit 0