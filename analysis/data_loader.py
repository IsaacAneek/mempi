#!/usr/bin/env python3
"""
Shared data-loading utilities for the mempi analysis scripts.

Parses:
  - meta.txt      → dict of experiment metadata
  - gpu_task.txt   → dict of GPU latency results
  - sysbench.txt   → dict with throughput time-series
  - dvfs.txt       → list[dict] of DVFS samples
  - v3d_counters.txt → DataFrame of V3D performance counters
"""

import os
import re
import sys
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Folder naming convention  →  stress parameters
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Folder & Scenario Parameter Parsing
# ---------------------------------------------------------------------------

def parse_block_bytes(block_str):
    """Convert block string (e.g., '16k', '4m', '256K') to integer bytes."""
    if not block_str or block_str in ("-", "none", "0"):
        return 0
    m = re.match(r"^(\d+)\s*(k|m|g)?i?b?$", str(block_str).strip(), re.IGNORECASE)
    if m:
        num, unit = m.groups()
        num = int(num)
        unit = (unit or "").lower()
        if unit == "k":
            return num * 1024
        elif unit == "m":
            return num * 1024 * 1024
        elif unit == "g":
            return num * 1024 * 1024 * 1024
        return num
    return 0


L3_BYTES_DEFAULT = 2 * 1024 * 1024   # BCM2712 shared L3 (documented value; verify on your system)


def format_bytes(n):
    """Format a byte count as KiB/MiB/GiB ('-' for 0)."""
    if not n:
        return "-"
    for unit, size in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if n >= size:
            val = n / size
            return f"{val:g} {unit}"
    return f"{n} B"


def parse_scenario(folder, meta=None):
    """
    Parse scenario metadata. Uses meta.txt if available, and falls back to folder name.
    Supports all 9 benchmark categories:
      - baseline
      - cache_resident  (e.g., 16kr, 256kr, 1mr)
      - cache_evict     (e.g., 2mr, 4mr)
      - dram_stream     (e.g., 8mr, 64mw)
      - dram_random     (e.g., 64mw_rnd, 8mr_rnd)
      - coherence       (e.g., 32kw_t2_g, 256kw_g)
      - thread_sweep    (e.g., 4mr_t2, 64mw_t8)
      - cpu_side        (e.g., 32kn, cpu_prime_t8, mutex1_t4, threads_t16)
      - pagefault       (e.g., pf_64mw_t4, ng_fault_t4)
    """
    if meta is None:
        try:
            meta = load_meta(folder)
        except Exception:
            meta = {}

    name = folder
    category = meta.get("category", "").strip()
    mode = meta.get("mode", "").strip()
    block_str = meta.get("block", "-").strip()
    oper = meta.get("oper", "-").strip()
    access = meta.get("access", "-").strip()
    threads_val = meta.get("threads", "-").strip()
    threads = int(threads_val) if threads_val.isdigit() else 4
    scope = meta.get("scope", "local").strip()

    # Fallback / inference if meta.txt did not have complete fields
    if not category:
        if name == "baseline":
            category = "baseline"
            mode = "none"
        elif name.startswith("mutex"):
            category = "cpu_side"
            mode = "mutex"
        elif name.startswith("cpu_prime"):
            category = "cpu_side"
            mode = "cpu"
        elif name.startswith("threads_"):
            category = "cpu_side"
            mode = "threads"
        elif name.startswith("pf_"):
            category = "pagefault"
            mode = "pf"
        elif name.startswith("ng_"):
            category = "pagefault"
            mode = "ngfault"
        elif "_g" in name:
            category = "coherence"
            scope = "global"
        elif "_t" in name:
            category = "thread_sweep"
        elif re.search(r"\d+(?:k|m)n", name):
            category = "cpu_side"
            oper = "none"
        else:
            category = "cache_resident"

    if block_str == "-" and mode not in ("mutex", "cpu", "threads", "ngfault"):
        m_block = re.search(r"(\d+)(k|m|g)", name, re.IGNORECASE)
        if m_block:
            block_str = m_block.group(1) + m_block.group(2).lower()

    if oper == "-":
        if "rw" in name:
            oper = "readwrite"
        elif re.search(r"\d+(?:k|m)r", name):
            oper = "read"
        elif re.search(r"\d+(?:k|m)w", name):
            oper = "write"
        elif re.search(r"\d+(?:k|m)n", name):
            oper = "none"

    if access == "-":
        access = "rnd" if "rnd" in name else "seq"

    if "_g" in name:
        scope = "global"

    m_t = re.search(r"_t(\d+)", name)
    if m_t:
        threads = int(m_t.group(1))

    block_bytes = parse_block_bytes(block_str)
    block_disp = block_str.upper() if block_str != "-" else "-"

    # Aggregate working set of the stressor.
    #   sysbench --memory-scope=local  : every thread owns one block -> block * threads
    #   sysbench --memory-scope=global : all threads share one block  -> block
    # Only computed for the sysbench modes ("mem" and the page-fault loop "pf");
    # for stress-ng modes the per-worker meaning of the byte size depends on the
    # stress-ng version, so no footprint is claimed.
    if mode in ("mem", "pf") and block_bytes > 0:
        footprint_bytes = block_bytes if scope == "global" else block_bytes * threads
    else:
        footprint_bytes = 0

    # Cache tier classification. These are HYPOTHESES from documented sizes of the
    # Cortex-A76 cluster in the BCM2712 (L1D 64 KiB/core, L2 512 KiB/core, L3 2 MiB
    # shared) and must be confirmed with measurements (see README). Rule used:
    #   cache_resident : each thread's block <= 256 KiB (half of its private L2)
    #                    AND the aggregate footprint <= L3 (2 MiB)
    #   l2_l3_resident : aggregate footprint <= L3 (2 MiB) but larger blocks
    #   cache_evict    : aggregate footprint > L3 (2 MiB)
    L3_BYTES = L3_BYTES_DEFAULT
    PRIVATE_BLOCK_LIMIT = 256 * 1024
    if category == "baseline":
        cache_tier = "baseline"
    elif category in ("cpu_side", "pagefault"):
        cache_tier = category
    elif footprint_bytes > 0:
        if block_bytes <= PRIVATE_BLOCK_LIMIT and footprint_bytes <= L3_BYTES:
            cache_tier = "cache_resident"
        elif footprint_bytes <= L3_BYTES:
            cache_tier = "l2_l3_resident"
        else:
            cache_tier = "cache_evict"
    else:
        cache_tier = category

    # Older meta.txt files were written when "1m" (4 threads -> 4 MiB, larger than the
    # 2 MiB L3) was listed as cache_resident. Correct that here so existing data is
    # classified by aggregate footprint, consistent with scripts/experiments.sh.
    if category == "cache_resident" and footprint_bytes > L3_BYTES:
        category = "cache_evict"

    return {
        "name": name,
        "category": category,
        "cache_tier": cache_tier,
        "mode": mode,
        "block_str": block_disp,
        "block_size_str": block_disp,
        "block_bytes": block_bytes,
        "footprint_bytes": footprint_bytes,
        "footprint_str": format_bytes(footprint_bytes),
        "oper": oper,
        "access": access,
        "threads": threads,
        "scope": scope,
    }


def parse_folder_name(name):
    """Backwards compatibility alias for parse_scenario."""
    return parse_scenario(name)


# ---------------------------------------------------------------------------
# meta.txt
# ---------------------------------------------------------------------------

def load_meta(folder):
    """Load meta.txt from a data folder."""
    path = DATA_DIR / folder / "meta.txt"
    meta = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("---"):
                break
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
    return meta


# ---------------------------------------------------------------------------
# gpu_task.txt  → GPU latency numbers
# ---------------------------------------------------------------------------

def load_gpu_task(folder):
    """
    Parse gpu_task.txt and return a dict with key latency numbers.

    Keys (all times in ms unless noted):
      e2e_ms            CPU wall time around the whole batch (400 dispatches + barriers
                        + glFinish), measured with CLOCK_MONOTONIC_RAW.
      gpu_elapsed_ms    GL_TIME_ELAPSED_EXT result for the batch = elapsed time on the
                        GPU timeline between the query boundaries. It includes the
                        dispatches AND the barriers inside the query, so it is not pure
                        shader execution time.
      compute_ms        alias of gpu_elapsed_ms (kept for the existing plots).
      e2e_minus_gpu_ms  SIGNED difference e2e_ms - gpu_elapsed_ms. This is NOT a dispatch
                        latency: CPU submission and GPU execution overlap, so the
                        difference mixes submission, synchronisation and timer effects.
                        Negative values are kept and flagged, never clamped.
      e2e_minus_gpu_us  the same, per dispatch (us).
      e2e_minus_gpu_pct the same, as % of e2e_ms (signed).
      negative_residual True if e2e_minus_gpu_ms < 0 (measurement disagreement; inspect).
      gpu_timer_disjoint True if the run reported an invalid (disjoint) GPU timer.
    """
    num = r"(-?\d+(?:\.\d+)?)"
    path = DATA_DIR / folder / "gpu_task.txt"
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            # End-to-end latency:          4605.335 ms
            m = re.match(rf"End-to-end latency:\s+{num}\s+ms", line)
            if m:
                result["e2e_ms"] = float(m.group(1))
            m = re.match(rf"Average per dispatch:\s+{num}\s+us", line)
            if m:
                result["avg_dispatch_us"] = float(m.group(1))
            m = re.match(rf"GPU elapsed time:\s+{num}\s+ms", line)
            if m:
                result["gpu_elapsed_ms"] = float(m.group(1))
            elif re.match(r"GPU elapsed time:\s+INVALID", line):
                result["gpu_timer_disjoint"] = True
            m = re.match(rf"Average GPU time/dispatch:\s+{num}\s+us", line)
            if m:
                result["avg_gpu_us"] = float(m.group(1))
            # signed: the regex accepts a leading '-'
            m = re.match(rf"E2E minus GPU elapsed:\s+{num}\s+ms", line)
            if m:
                result["printed_e2e_minus_gpu_ms"] = float(m.group(1))
            m = re.match(r"Dispatch count:\s+(\d+)", line)
            if m:
                result["dispatch_count"] = int(m.group(1))

    if "e2e_ms" in result and "gpu_elapsed_ms" in result:
        result["compute_ms"] = result["gpu_elapsed_ms"]

        # Signed residual: prefer the value gpu_task printed, else compute it. No clamping.
        resid = result.get("printed_e2e_minus_gpu_ms",
                           result["e2e_ms"] - result["gpu_elapsed_ms"])
        result["e2e_minus_gpu_ms"] = resid
        result["negative_residual"] = resid < 0

        count = result.get("dispatch_count", 400)
        result["e2e_minus_gpu_us"] = (resid * 1000.0) / count if count > 0 else 0.0
        result["e2e_minus_gpu_pct"] = (resid / result["e2e_ms"] * 100.0) if result["e2e_ms"] > 0 else 0.0
    return result


# ---------------------------------------------------------------------------
# sysbench.txt  →  throughput time-series (MiB/sec)
# ---------------------------------------------------------------------------

def load_sysbench(folder):
    """Parse sysbench.txt – return (info_dict, throughput_series)."""
    path = DATA_DIR / folder / "sysbench.txt"
    info = {}
    throughput = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            # block size: 4096KiB
            m = re.match(r"block size:\s+(\d+)KiB", line)
            if m:
                info["block_kib"] = int(m.group(1))
            m = re.match(r"operation:\s+(\w+)", line)
            if m:
                info["operation"] = m.group(1)
            m = re.match(r"scope:\s+(\w+)", line)
            if m:
                info["scope"] = m.group(1)
            m = re.match(r"Number of threads:\s+(\d+)", line)
            if m:
                info["threads"] = int(m.group(1))
            # [ 1s ] 11172.56 MiB/sec
            m = re.match(r"\[\s*(\d+)s\s*\]\s+([\d.]+)\s+MiB/sec", line)
            if m:
                throughput.append({
                    "second": int(m.group(1)),
                    "mib_per_sec": float(m.group(2)),
                })
    return info, pd.DataFrame(throughput) if throughput else pd.DataFrame()


# ---------------------------------------------------------------------------
# dvfs.txt  →  list of DVFS sample dicts
# ---------------------------------------------------------------------------

def load_dvfs(folder):
    """
    Parse dvfs.txt log lines.  Returns a DataFrame with columns:
    timestamp, elapsed_s, cpu_khz, arm_hz, v3d_hz, temp_c, gpu_state, throttled
    """
    path = DATA_DIR / folder / "dvfs.txt"
    samples = []
    pattern = re.compile(
        r"\[([^\]]+)\]\s+elapsed=(\d+)s\s+"
        r"CPU=(\d+)\s+kHz\s+"
        r"ARM=(\d+)\s+Hz\s+"
        r"V3D=(\d*)\s+Hz\s+"
        r"temp=([\d.]+)\s+C\s+"
        r"GPU=(\w+)\s+"
        r"throttled=(0x[0-9a-fA-F]+)"
    )

    with open(path) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                samples.append({
                    "timestamp": m.group(1),
                    "elapsed_s": int(m.group(2)),
                    "cpu_khz": int(m.group(3)),
                    "arm_hz": int(m.group(4)),
                    "v3d_hz": int(m.group(5)) if m.group(5) else 0,
                    "temp_c": float(m.group(6)),
                    "gpu_state": m.group(7),
                    "throttled": m.group(8),
                })

    return pd.DataFrame(samples)


# ---------------------------------------------------------------------------
# v3d_counters.txt  →  DataFrame
# ---------------------------------------------------------------------------

def load_v3d_counters(folder):
    """
    Parse v3d_counters.txt.
    Returns a DataFrame with columns:
      wall_epoch, elapsed_s, window, group, counter_id, counter_name, value
    """
    path = DATA_DIR / folder / "v3d_counters.txt"
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            try:
                rows.append({
                    "wall_epoch": float(parts[0]),
                    "elapsed_s": float(parts[1]),
                    "window": int(parts[2]),
                    "group": int(parts[3]),
                    "counter_id": int(parts[4]),
                    "counter_name": parts[5],
                    "value": int(parts[6]),
                })
            except (ValueError, IndexError):
                continue
    return pd.DataFrame(rows)


def get_active_v3d(folder):
    """
    Return only the V3D counter windows that overlap with GPU activity
    (value > 0 for at least one counter in the window).
    Pivots into a wide-format DataFrame: one row per window, one column per counter.
    """
    df = load_v3d_counters(folder)
    if df.empty:
        return df

    # Sum values per window – keep windows where the GPU was doing work
    window_totals = df.groupby("window")["value"].sum()
    active_windows = window_totals[window_totals > 0].index

    active = df[df["window"].isin(active_windows)].copy()

    # Pivot to wide format
    wide = active.pivot_table(
        index="window", columns="counter_name", values="value", aggfunc="sum"
    ).fillna(0)
    return wide


# ---------------------------------------------------------------------------
# Load all scenarios at once
# ---------------------------------------------------------------------------

def discover_scenarios():
    """Return list of folder names in data/, excluding hidden."""
    return sorted([
        d.name for d in DATA_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])


def load_all():
    """
    Load every scenario.  Returns a list of dicts, each containing:
      folder, params, meta, gpu, sysbench_info, sysbench_throughput, dvfs, v3d
    """
    results = []
    for folder in discover_scenarios():
        try:
            meta = load_meta(folder)
        except (FileNotFoundError, Exception):
            meta = {}
        params = parse_scenario(folder, meta)
        gpu = load_gpu_task(folder)
        sb_info, sb_tp = load_sysbench(folder)
        dvfs = load_dvfs(folder)
        v3d = load_v3d_counters(folder)
        if gpu.get("negative_residual"):
            print(f"WARNING: {folder}: E2E - GPU timer is negative "
                  f"({gpu['e2e_minus_gpu_ms']:.3f} ms); kept as-is, please inspect.",
                  file=sys.stderr)
        results.append({
            "folder": folder,
            "params": params,
            "meta": meta,
            "gpu": gpu,
            "sysbench_info": sb_info,
            "sysbench_throughput": sb_tp,
            "dvfs": dvfs,
            "v3d": v3d,
        })
    return results


if __name__ == "__main__":
    # Quick test
    all_s = load_all()
    print(f"{'Folder':<14s} {'Category':<15s} {'Mode':<8s} {'Block':>6s} {'Thr':>4s} {'Scope':<7s} "
          f"{'Footprint':>10s} {'E2E (ms)':>10s} {'GPUtimer(ms)':>12s} {'E2E-GPU(ms)':>12s} {'%E2E':>8s}")
    print("-" * 125)
    for s in all_s:
        p = s["params"]
        g = s["gpu"]
        e2e = g.get('e2e_ms', 0)
        comp = g.get('compute_ms', 0)
        resid = g.get('e2e_minus_gpu_ms', 0)
        resid_pct = g.get('e2e_minus_gpu_pct', 0)
        flag = "  <-- NEGATIVE" if g.get('negative_residual') else ""
        print(f"{s['folder']:<14s} {p['category']:<15s} {p['mode']:<8s} {p['block_str']:>6s} {str(p['threads']):>4s} "
              f"{p['scope']:<7s} {p['footprint_str']:>10s} {e2e:>10.1f} {comp:>12.1f} {resid:>12.3f} {resid_pct:>7.4f}%{flag}")