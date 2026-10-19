
#!/usr/bin/env bash
#
# rpi5-dvfs-monitor.sh
#
# Monitor Raspberry Pi 5 CPU/GPU clocks, thermal behavior, throttling,
# runtime power management, V3D job statistics, and CPU frequency policies.
#
# Usage:
#   chmod +x rpi5-dvfs-monitor.sh
#   ./rpi5-dvfs-monitor.sh
#   ./rpi5-dvfs-monitor.sh 0.5
#   ./rpi5-dvfs-monitor.sh 1 60
#
# Arguments:
#   $1 = sampling interval in seconds (default: 1)
#   $2 = duration in seconds; 0 means run until Ctrl+C (default: 0)
#
# Output:
#   rpi5-dvfs-logs/<timestamp>/
#       monitor.csv
#       cpu_policies.csv
#       thermal_zones.csv
#       gpu_stats.tsv
#       runtime_pm.csv
#       system_info.txt

set -uo pipefail

INTERVAL="${1:-1}"
DURATION="${2:-0}"

if ! command -v vcgencmd >/dev/null 2>&1; then
    echo "ERROR: vcgencmd not found. Install/use the Raspberry Pi firmware tools." >&2
    exit 1
fi

if ! command -v awk >/dev/null 2>&1; then
    echo "ERROR: awk is required." >&2
    exit 1
fi

if ! awk -v n="$INTERVAL" 'BEGIN { exit !(n > 0) }'; then
    echo "ERROR: sampling interval must be greater than zero." >&2
    exit 1
fi

if ! [[ "$DURATION" =~ ^[0-9]+$ ]]; then
    echo "ERROR: duration must be a non-negative integer." >&2
    exit 1
fi

BASE_DIR="rpi5-dvfs-logs"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
OUT_DIR="${BASE_DIR}/${RUN_ID}"

mkdir -p "$OUT_DIR" || exit 1

GPU_SYS="/sys/devices/platform/axi/1002000000.v3d"
GPU_POWER="${GPU_SYS}/power"
GPU_STATS="${GPU_SYS}/gpu_stats"

timestamp() {
    date '+%Y-%m-%dT%H:%M:%S.%3N%:z'
}

read_value() {
    local file="$1"

    if [[ -r "$file" ]]; then
        tr '\n' ' ' < "$file" | sed 's/[[:space:]]*$//'
    else
        printf 'NA'
    fi
}

vcg_output() {
    timeout 2 vcgencmd "$@" 2>/dev/null || printf 'NA'
}

# Extract the number after '=' from output such as frequency(0)=960000000.
vcg_number() {
    local output
    output="$(vcg_output "$@")"

    if [[ "$output" =~ =([0-9]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    else
        printf 'NA'
    fi
}

# Extract throttling flags from output such as throttled=0x0.
throttle_value() {
    local output
    output="$(vcg_output get_throttled)"

    if [[ "$output" =~ throttled=(0x[[:xdigit:]]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    else
        printf 'NA'
    fi
}

# CSV-safe field output.
csv_field() {
    local value="${1:-NA}"
    value="${value//\"/\"\"}"
    printf '"%s"' "$value"
}

echo "Creating logs in: $OUT_DIR"
echo "Sampling interval: ${INTERVAL}s"
echo "Duration: ${DURATION}s (0 = until Ctrl+C)"
echo

# Record system configuration and environment once.
{
    echo "Collection started: $(timestamp)"
    echo "Hostname: $(hostname)"
    echo "Kernel: $(uname -a)"
    echo
    echo "=== OS release ==="
    cat /etc/os-release 2>/dev/null || true
    echo
    echo "=== CPU information ==="
    lscpu 2>/dev/null || true
    echo
    echo "=== V3D device ==="
    readlink -f "$GPU_SYS" 2>/dev/null || true
    echo
    echo "=== vcgencmd version ==="
    vcg_output version
    echo
    echo "=== Initial throttling status ==="
    vcg_output get_throttled
    echo
    echo "=== Initial clock readings ==="
    for clock in arm v3d core; do
        printf '%s: ' "$clock"
        vcg_output measure_clock "$clock"
    done
    echo
    echo "=== GPU stats file ==="
    ls -l "$GPU_STATS" 2>/dev/null || true
} > "$OUT_DIR/system_info.txt"

# Main CSV: one row per sampling iteration.
cat > "$OUT_DIR/monitor.csv" <<'EOF'
timestamp,elapsed_seconds,cpu0_clock_khz,cpu0_governor,cpu0_min_khz,cpu0_max_khz,arm_clock_hz,v3d_clock_hz,core_clock_hz,temperature_c,throttled_flags,gpu_runtime_status,gpu_runtime_active_time,gpu_runtime_suspended_time,gpu_bo_count,gpu_bo_size_kb
EOF

cat > "$OUT_DIR/cpu_policies.csv" <<'EOF'
timestamp,policy,related_cpus,scaling_cur_freq_khz,scaling_min_freq_khz,scaling_max_freq_khz,scaling_governor
EOF

cat > "$OUT_DIR/thermal_zones.csv" <<'EOF'
timestamp,zone,type,temp_raw,trip_points
EOF

cat > "$OUT_DIR/runtime_pm.csv" <<'EOF'
timestamp,gpu_runtime_status,runtime_active_time,runtime_suspended_time
EOF

# Preserve every gpu_stats snapshot, including its original header.
{
    printf '# Collection started: %s\n' "$(timestamp)"
    printf '# Source: %s\n' "$GPU_STATS"
} > "$OUT_DIR/gpu_stats.tsv"

START_SECONDS="$(date +%s)"
SAMPLE=0

cleanup() {
    echo
    echo "Monitoring stopped."
    echo "Samples recorded: $SAMPLE"
    echo "Logs saved to: $OUT_DIR"
}
trap cleanup EXIT INT TERM

echo "Monitoring started. Press Ctrl+C to stop."
echo

while true; do
    NOW="$(timestamp)"
    CURRENT_SECONDS="$(date +%s)"
    ELAPSED="$((CURRENT_SECONDS - START_SECONDS))"

    # CPU policy: use policy0 for the main CSV if available.
    POLICY0="/sys/devices/system/cpu/cpufreq/policy0"

    CPU0_FREQ="$(read_value "${POLICY0}/scaling_cur_freq")"
    CPU0_GOV="$(read_value "${POLICY0}/scaling_governor")"
    CPU0_MIN="$(read_value "${POLICY0}/scaling_min_freq")"
    CPU0_MAX="$(read_value "${POLICY0}/scaling_max_freq")"

    ARM_CLOCK="$(vcg_number measure_clock arm)"
    V3D_CLOCK="$(vcg_number measure_clock v3d)"
    CORE_CLOCK="$(vcg_number measure_clock core)"

    TEMP_OUTPUT="$(vcg_output measure_temp)"
    if [[ "$TEMP_OUTPUT" =~ temp=([-+]?[0-9]+([.][0-9]+)?) ]]; then
        TEMP_C="${BASH_REMATCH[1]}"
    else
        TEMP_C="NA"
    fi

    THROTTLED="$(throttle_value)"

    GPU_STATUS="$(read_value "${GPU_POWER}/runtime_status")"
    GPU_ACTIVE="$(read_value "${GPU_POWER}/runtime_active_time")"
    GPU_SUSPENDED="$(read_value "${GPU_POWER}/runtime_suspended_time")"

    BO_COUNT="NA"
    BO_SIZE="NA"

    BO_STATS="/sys/kernel/debug/dri/0/bo_stats"
    if [[ -r "$BO_STATS" ]]; then
        BO_COUNT="$(awk '/allocated bos:/ {print $3; exit}' "$BO_STATS")"
        BO_SIZE="$(awk '/allocated bo size \(kb\):/ {print $5; exit}' "$BO_STATS")"
        BO_COUNT="${BO_COUNT:-NA}"
        BO_SIZE="${BO_SIZE:-NA}"
    fi

    {
        csv_field "$NOW"; printf ','
        csv_field "$ELAPSED"; printf ','
        csv_field "$CPU0_FREQ"; printf ','
        csv_field "$CPU0_GOV"; printf ','
        csv_field "$CPU0_MIN"; printf ','
        csv_field "$CPU0_MAX"; printf ','
        csv_field "$ARM_CLOCK"; printf ','
        csv_field "$V3D_CLOCK"; printf ','
        csv_field "$CORE_CLOCK"; printf ','
        csv_field "$TEMP_C"; printf ','
        csv_field "$THROTTLED"; printf ','
        csv_field "$GPU_STATUS"; printf ','
        csv_field "$GPU_ACTIVE"; printf ','
        csv_field "$GPU_SUSPENDED"; printf ','
        csv_field "$BO_COUNT"; printf ','
        csv_field "$BO_SIZE"; printf '\n'
    } >> "$OUT_DIR/monitor.csv"

    # Log every CPU frequency policy, not only policy0.
    for policy_dir in /sys/devices/system/cpu/cpufreq/policy*; do
        [[ -d "$policy_dir" ]] || continue

        POLICY_NAME="${policy_dir##*/}"
        RELATED="$(read_value "${policy_dir}/related_cpus")"
        CUR="$(read_value "${policy_dir}/scaling_cur_freq")"
        MIN="$(read_value "${policy_dir}/scaling_min_freq")"
        MAX="$(read_value "${policy_dir}/scaling_max_freq")"
        GOV="$(read_value "${policy_dir}/scaling_governor")"

        {
            csv_field "$NOW"; printf ','
            csv_field "$POLICY_NAME"; printf ','
            csv_field "$RELATED"; printf ','
            csv_field "$CUR"; printf ','
            csv_field "$MIN"; printf ','
            csv_field "$MAX"; printf ','
            csv_field "$GOV"; printf '\n'
        } >> "$OUT_DIR/cpu_policies.csv"
    done

    # Log each available thermal zone.
    for zone_dir in /sys/class/thermal/thermal_zone*; do
        [[ -d "$zone_dir" ]] || continue

        ZONE="${zone_dir##*/}"
        TYPE="$(read_value "${zone_dir}/type")"
        ZONE_TEMP="$(read_value "${zone_dir}/temp")"
        TRIPS=""

        for trip_file in "${zone_dir}"/trip_point_*_temp; do
            [[ -r "$trip_file" ]] || continue
            TRIP_NAME="${trip_file##*/}"
            TRIP_VALUE="$(read_value "$trip_file")"
            TRIPS+="${TRIP_NAME}=${TRIP_VALUE};"
        done

        {
            csv_field "$NOW"; printf ','
            csv_field "$ZONE"; printf ','
            csv_field "$TYPE"; printf ','
            csv_field "$ZONE_TEMP"; printf ','
            csv_field "$TRIPS"; printf '\n'
        } >> "$OUT_DIR/thermal_zones.csv"
    done

    # Keep raw runtime power-management counters in a separate file.
    {
        csv_field "$NOW"; printf ','
        csv_field "$GPU_STATUS"; printf ','
        csv_field "$GPU_ACTIVE"; printf ','
        csv_field "$GPU_SUSPENDED"; printf '\n'
    } >> "$OUT_DIR/runtime_pm.csv"

    # Append a timestamp and the complete GPU queue-statistics snapshot.
    {
        printf '\n# timestamp=%s elapsed_seconds=%s\n' "$NOW" "$ELAPSED"
        if [[ -r "$GPU_STATS" ]]; then
            cat "$GPU_STATS"
        else
            printf 'gpu_stats_unavailable\n'
        fi
    } >> "$OUT_DIR/gpu_stats.tsv"

    SAMPLE=$((SAMPLE + 1))

    # Print a compact live status line.
    printf '[%s] elapsed=%ss CPU=%s kHz ARM=%s Hz V3D=%s Hz temp=%s C GPU=%s throttled=%s\n' \
        "$NOW" "$ELAPSED" "$CPU0_FREQ" "$ARM_CLOCK" "$V3D_CLOCK" \
        "$TEMP_C" "$GPU_STATUS" "$THROTTLED"

    if (( DURATION > 0 && ELAPSED >= DURATION )); then
        break
    fi

    sleep "$INTERVAL"
done
