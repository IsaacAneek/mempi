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
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Folder naming convention  →  stress parameters
# ---------------------------------------------------------------------------

def parse_folder_name(name):
    """
    Parse a folder name like '4mr', '16kr', '16kr_rnd' into structured params.
    Returns dict with keys: block_size_str, block_bytes, oper, access.
    """
    if name == "baseline":
        return {
            "name": "baseline",
            "block_size_str": "-",
            "block_bytes": 0,
            "oper": "none",
            "access": "seq",
            "category": "baseline",
        }

    # e.g. 4mr  →  block=4m oper=r
    #      16kr →  block=16k oper=r
    #      16kr_rnd → block=16k oper=r access=rnd
    m = re.match(r"^(\d+)(k|m)(r|w|rw)(?:_(seq|rnd))?$", name, re.IGNORECASE)
    if not m:
        return None

    num, unit, oper, access = m.groups()
    num = int(num)
    unit = unit.lower()
    block_bytes = num * (1024 if unit == "k" else 1024 * 1024)
    oper_map = {"r": "read", "w": "write", "rw": "readwrite"}
    # Category based on RPi5 cache hierarchy (L1=256K, L2=2M, L3=2M)
    if block_bytes <= 256 * 1024:
        cat = "cache_resident"
    elif block_bytes <= 2 * 1024 * 1024:
        cat = "l2_l3_resident"
    else:
        cat = "cache_evict"

    return {
        "name": name,
        "block_size_str": f"{num}{unit.upper()}",
        "block_bytes": block_bytes,
        "oper": oper_map.get(oper, oper),
        "access": access or "seq",
        "category": cat,
    }


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
    """Parse gpu_task.txt and return a dict with key latency numbers."""
    path = DATA_DIR / folder / "gpu_task.txt"
    result = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            # End-to-end latency:          4605.335 ms
            m = re.match(r"End-to-end latency:\s+([\d.]+)\s+ms", line)
            if m:
                result["e2e_ms"] = float(m.group(1))
            m = re.match(r"Average per dispatch:\s+([\d.]+)\s+us", line)
            if m:
                result["avg_dispatch_us"] = float(m.group(1))
            m = re.match(r"GPU elapsed time:\s+([\d.]+)\s+ms", line)
            if m:
                result["gpu_elapsed_ms"] = float(m.group(1))
            m = re.match(r"Average GPU time/dispatch:\s+([\d.]+)\s+us", line)
            if m:
                result["avg_gpu_us"] = float(m.group(1))
            m = re.match(r"E2E minus GPU elapsed:\s+([\d.]+)\s+ms", line)
            if m:
                result["overhead_ms"] = float(m.group(1))
            m = re.match(r"Dispatch count:\s+(\d+)", line)
            if m:
                result["dispatch_count"] = int(m.group(1))

    # Standardize compute latency and dispatch latency (E2E - compute)
    if "e2e_ms" in result and "gpu_elapsed_ms" in result:
        result["compute_ms"] = result["gpu_elapsed_ms"]
        # Dispatch latency is E2E minus compute (GPU elapsed)
        disp_ms = result.get("overhead_ms", result["e2e_ms"] - result["gpu_elapsed_ms"])
        result["dispatch_latency_ms"] = max(disp_ms, 0.0)
        result["overhead_ms"] = result["dispatch_latency_ms"]
        
        count = result.get("dispatch_count", 400)
        result["dispatch_latency_us"] = (result["dispatch_latency_ms"] * 1000.0) / count if count > 0 else 0.0
        result["dispatch_ratio_pct"] = (result["dispatch_latency_ms"] / result["e2e_ms"] * 100.0) if result["e2e_ms"] > 0 else 0.0
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
        params = parse_folder_name(folder)
        if params is None:
            continue
        try:
            meta = load_meta(folder)
        except FileNotFoundError:
            meta = {}
        gpu = load_gpu_task(folder)
        sb_info, sb_tp = load_sysbench(folder)
        dvfs = load_dvfs(folder)
        v3d = load_v3d_counters(folder)
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
    print(f"{'Folder':<12s} {'Block':>6s} {'E2E (ms)':>10s} {'Compute (ms)':>12s} {'Dispatch (ms)':>14s} {'Disp/iter (us)':>15s} {'Disp %':>8s}")
    print("-" * 82)
    for s in all_s:
        p = s["params"]
        g = s["gpu"]
        e2e = g.get('e2e_ms', 0)
        comp = g.get('compute_ms', 0)
        disp = g.get('dispatch_latency_ms', 0)
        disp_us = g.get('dispatch_latency_us', 0)
        disp_pct = g.get('dispatch_ratio_pct', 0)
        print(f"{s['folder']:<12s} {p['block_size_str']:>6s} {e2e:>10.1f} {comp:>12.1f} {disp:>14.3f} {disp_us:>15.3f} {disp_pct:>7.3f}%")

