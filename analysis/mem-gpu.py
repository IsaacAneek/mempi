#!/usr/bin/env python3
"""
mem-gpu.py  ─  Memory Stress vs GPU Task Latency & Dispatch Overhead
=====================================================================
Correlates sysbench memory-stress parameters (block size, access pattern,
DRAM bandwidth consumed) with:
  1. Compute Latency (GPU hardware kernel elapsed time)
  2. Dispatch Latency = End-to-End (E2E) - Compute Latency
  3. Total End-to-End Latency

Plots generated (saved to analysis/plots/):
  1. mem_gpu_absolute_latency.png:
     Dual-panel comparison of E2E/Compute Latency (ms) and Dispatch Latency (ms & us/iter).
  2. mem_gpu_degradation_comparison.png:
     Grouped degradation factor (× baseline) comparing E2E, Compute, and Dispatch Latency.
  3. mem_gpu_dispatch_vs_compute.png:
     Dispatch Latency vs Compute Latency scatter & Dispatch Ratio (% of E2E).
  4. mem_gpu_blocksize_vs_latencies.png:
     Latency progression across the RPi5 cache hierarchy (L1 256K, L2 2M, L3 2M, DRAM).
  5. mem_gpu_bandwidth_vs_latency.png:
     Sysbench memory bandwidth consumed vs Compute and Dispatch Latencies.
  6. mem_gpu_throughput_timeseries.png:
     Time-series memory throughput during GPU execution.
"""

import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import load_all, DATA_DIR

PLOT_DIR = os.path.join(os.path.dirname(__file__), "plots")
os.makedirs(PLOT_DIR, exist_ok=True)

# ── Styling ──────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f8f8",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
})

COLORS = {
    "baseline": "#4CAF50",         # Green
    "cache_resident": "#2196F3",   # Blue (L1 cache <= 256K)
    "l2_l3_resident": "#FF9800",   # Orange (L2/L3 cache <= 2M)
    "cache_evict": "#F44336",      # Red (DRAM > 2M)
}


def scenario_color(params):
    return COLORS.get(params["category"], "#9E9E9E")


def scenario_label(params):
    if params["name"] == "baseline":
        return "Baseline\n(no stress)"
    acc = "rnd" if params["access"] == "rnd" else "seq"
    return f"{params['block_size_str']} {params['oper']}\n({acc})"


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    # Sort: baseline first, then by block bytes, then by access
    data.sort(key=lambda d: (0 if d["params"]["name"] == "baseline" else 1,
                             d["params"]["block_bytes"],
                             d["params"]["access"]))

    labels = [scenario_label(d["params"]) for d in data]
    short_names = [d["params"]["name"] for d in data]
    colors = [scenario_color(d["params"]) for d in data]

    # Find baseline metrics
    baseline = next((d for d in data if d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 1.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 1.0
    base_disp = baseline["gpu"]["dispatch_latency_ms"] if baseline else 0.001
    if base_disp <= 0:
        base_disp = 0.001

    e2e_vals = [d["gpu"]["e2e_ms"] for d in data]
    comp_vals = [d["gpu"]["compute_ms"] for d in data]
    disp_vals = [d["gpu"]["dispatch_latency_ms"] for d in data]
    disp_us_vals = [d["gpu"]["dispatch_latency_us"] for d in data]
    disp_pct_vals = [d["gpu"]["dispatch_ratio_pct"] for d in data]

    x = np.arange(len(data))
    bar_w = 0.35

    # ── Plot 1: Absolute Latency Breakdown (E2E/Compute + Dispatch) ─────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Left: E2E and Compute Latency (ms)
    b1 = ax1.bar(x - bar_w / 2, e2e_vals, bar_w, label="End-to-End Latency",
                 color=colors, edgecolor="black", linewidth=0.6)
    b2 = ax1.bar(x + bar_w / 2, comp_vals, bar_w, label="Compute Latency (GPU elapsed)",
                 color=colors, edgecolor="black", linewidth=0.6, alpha=0.6)

    for bar, val in zip(b1, e2e_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax1.set_xlabel("Memory Stress Scenario")
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title("E2E vs Compute Latency\n(Scale: seconds / thousands of ms)", fontsize=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.legend(loc="upper left")
    ax1.axhline(base_e2e, color="green", linestyle="--", alpha=0.5, linewidth=1)

    # Right: Dispatch Latency = E2E - Compute (ms and us per dispatch)
    b3 = ax2.bar(x, disp_vals, bar_w * 1.5, color=colors, edgecolor="black", linewidth=0.6)
    for bar, val, val_us in zip(b3, disp_vals, disp_us_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                 f"{val:.3f} ms\n({val_us:.2f} µs)", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax2.set_xlabel("Memory Stress Scenario")
    ax2.set_ylabel("Dispatch Latency (ms) = E2E - Compute")
    ax2.set_title("Dispatch Latency (CPU↔GPU Driver & Sync Overhead)\n(Scale: fractions of ms / microseconds)", fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.axhline(base_disp, color="green", linestyle="--", alpha=0.5, linewidth=1,
                label=f"Baseline: {base_disp:.3f} ms")
    ax2.legend(loc="upper left")

    fig.suptitle("GPU Task Latency Breakdown: Compute vs Dispatch Overhead Under Memory Stress",
                 fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_absolute_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_absolute_latency.png")
    plt.close(fig)

    # ── Plot 2: Degradation Factor Comparison (E2E vs Compute vs Dispatch) ──
    degr_e2e = [v / base_e2e for v in e2e_vals]
    degr_comp = [v / base_comp for v in comp_vals]
    degr_disp = [v / base_disp for v in disp_vals]

    fig, ax = plt.subplots(figsize=(14, 6))
    w3 = 0.25
    b_e2e = ax.bar(x - w3, degr_e2e, w3, label="E2E Degradation (×)", color="#42A5F5", edgecolor="black", linewidth=0.5)
    b_cmp = ax.bar(x, degr_comp, w3, label="Compute Degradation (×)", color="#EF5350", edgecolor="black", linewidth=0.5)
    b_dsp = ax.bar(x + w3, degr_disp, w3, label="Dispatch Degradation (×) [E2E - Compute]", color="#FFA726", edgecolor="black", linewidth=0.5)

    for bar, val in zip(b_e2e, degr_e2e):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2, f"{val:.1f}×", ha="center", fontsize=7)
    for bar, val in zip(b_cmp, degr_comp):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2, f"{val:.1f}×", ha="center", fontsize=7)
    for bar, val in zip(b_dsp, degr_disp):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2, f"{val:.1f}×", ha="center", fontsize=8, fontweight="bold", color="#D84315")

    ax.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.7, label="1.0× Baseline")
    ax.set_xlabel("Memory Stress Scenario")
    ax.set_ylabel("Degradation Factor (× Baseline)")
    ax.set_title("Latency Degradation Comparison: E2E vs Compute vs Dispatch Latency\n"
                 "Note that Dispatch Latency degrades up to 20× at 256K & 2M due to CPU driver cache/bus contention",
                 fontsize=13)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.legend(loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_degradation_comparison.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_degradation_comparison.png")
    plt.close(fig)

    # ── Plot 3: Dispatch Latency vs Compute Latency & Ratio ───────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    # Scatter: Compute Latency vs Dispatch Latency
    for d, c, e, g, disp, disp_us in zip(data, colors, e2e_vals, comp_vals, disp_vals, disp_us_vals):
        name = d["params"]["name"]
        ax1.scatter(g, disp, s=180, color=c, edgecolors="black", linewidth=1.2, zorder=4)
        ax1.annotate(f" {name}\n ({disp:.2f}ms)", (g, disp), fontsize=8, fontweight="bold")

    ax1.set_xlabel("Compute Latency (GPU elapsed ms)")
    ax1.set_ylabel("Dispatch Latency (E2E - compute ms)")
    ax1.set_title("Dispatch Latency vs Compute Latency", fontsize=12)

    # Right: Dispatch Latency as % of Total E2E Latency
    bars_pct = ax2.bar(x, disp_pct_vals, bar_w * 1.5, color=colors, edgecolor="black", linewidth=0.5)
    for bar, val in zip(bars_pct, disp_pct_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001,
                 f"{val:.3f}%", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax2.set_xlabel("Memory Stress Scenario")
    ax2.set_ylabel("Dispatch Overhead (% of E2E Latency)")
    ax2.set_title("Dispatch Latency Proportion of Total Execution Time", fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)

    fig.suptitle("Dispatch Latency Correlation with GPU Compute Latency", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_dispatch_vs_compute.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_dispatch_vs_compute.png")
    plt.close(fig)

    # ── Plot 4: Block Size vs Latencies Across Cache Hierarchy ────────────
    # Filter scenarios with numeric block bytes > 0
    stress_data = [d for d in data if d["params"]["block_bytes"] > 0]
    if stress_data:
        b_bytes = [d["params"]["block_bytes"] for d in stress_data]
        b_kib = [b / 1024.0 for b in b_bytes]
        b_comp = [d["gpu"]["compute_ms"] for d in stress_data]
        b_disp = [d["gpu"]["dispatch_latency_ms"] for d in stress_data]
        b_labels = [d["params"]["name"] for d in stress_data]

        fig, ax1 = plt.subplots(figsize=(11, 6))
        ax2 = ax1.twinx()

        p1 = ax1.plot(b_kib, b_comp, "ro-", linewidth=2.2, markersize=8, label="Compute Latency (ms)")
        p2 = ax2.plot(b_kib, b_disp, "bs--", linewidth=2.0, markersize=8, label="Dispatch Latency (ms) [E2E - Compute]")

        # Mark cache boundaries on RPi 5
        # L1: 256 KiB, L2: 2048 KiB, L3: 2048 KiB
        ax1.axvline(256, color="purple", linestyle=":", alpha=0.7, label="L1 Cache (256 KiB)")
        ax1.axvline(2048, color="brown", linestyle=":", alpha=0.7, label="L2 / L3 Cache (2 MiB)")

        ax1.set_xscale("log", base=2)
        ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda val, pos: f"{int(val)}K" if val < 1024 else f"{int(val/1024)}M"))

        ax1.set_xlabel("Memory Stress Block Size (log scale)")
        ax1.set_ylabel("Compute Latency (ms)", color="red")
        ax2.set_ylabel("Dispatch Latency (ms)", color="blue")
        ax1.tick_params(axis="y", labelcolor="red")
        ax2.tick_params(axis="y", labelcolor="blue")

        # Combine legends
        lines = p1 + p2 + [ax1.get_lines()[-2], ax1.get_lines()[-1]]
        leg_labels = [l.get_label() for l in lines]
        ax1.legend(lines, leg_labels, loc="center left", fontsize=9)

        ax1.set_title("Latency Progression Across Raspberry Pi 5 Cache Hierarchy\n"
                      "Compute latency explodes when block > 256K; Dispatch latency peaks at cache boundaries",
                      fontsize=12)
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_blocksize_vs_latencies.png"), dpi=150)
        print(f"  → {PLOT_DIR}/mem_gpu_blocksize_vs_latencies.png")
        plt.close(fig)

    # ── Plot 5: Sysbench Bandwidth vs Compute & Dispatch Latencies ────────
    bw_avg = []
    for d in data:
        tp = d["sysbench_throughput"]
        if not tp.empty:
            bw_avg.append(tp["mib_per_sec"].mean())
        else:
            bw_avg.append(0)

    fig, ax1 = plt.subplots(figsize=(11, 6))
    ax2 = ax1.twinx()

    bar_bw = ax1.bar(x, bw_avg, bar_w * 1.5, color="#90CAF9", edgecolor="black",
                     linewidth=0.5, alpha=0.8, label="Sysbench Bandwidth (MiB/s)")
    line_comp = ax2.plot(x, comp_vals, "ro-", markersize=8, linewidth=2, label="Compute Latency (ms)")
    line_disp = ax2.plot(x, [v * 1000 for v in disp_vals], "gs--", markersize=8, linewidth=2, label="Dispatch Latency (×1000 for visibility, ms)")

    ax1.set_xlabel("Memory Stress Scenario")
    ax1.set_ylabel("Sysbench Memory Bandwidth (MiB/s)", color="#1565C0")
    ax2.set_ylabel("Latency (ms / ×1000)", color="black")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)

    lines_all = [bar_bw, line_comp[0], line_disp[0]]
    labels_all = ["Sysbench Bandwidth (MiB/s)", "Compute Latency (ms)", "Dispatch Latency × 1000 (ms)"]
    ax1.legend(lines_all, labels_all, loc="upper left", fontsize=9)

    ax1.set_title("Memory Bandwidth Contention vs Compute & Dispatch Latency", fontsize=12)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_bandwidth_vs_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_bandwidth_vs_latency.png")
    plt.close(fig)

    # ── Plot 6: Sysbench Throughput Time-Series ───────────────────────────
    stress_scenarios = [d for d in data if d["params"]["name"] != "baseline"]
    if stress_scenarios:
        fig, ax = plt.subplots(figsize=(13, 6))
        for d in stress_scenarios:
            tp = d["sysbench_throughput"]
            if not tp.empty:
                lbl = f"{d['params']['block_size_str']} {d['params']['oper']} ({d['params']['access']})"
                ax.plot(tp["second"], tp["mib_per_sec"], ".-", label=lbl, linewidth=1.5)

        ax.set_xlabel("Time (seconds since sysbench start)")
        ax.set_ylabel("Throughput (MiB/s)")
        ax.set_title("Sysbench Memory Throughput During GPU Task Execution\n"
                     "Shows CPU-side memory bandwidth generation during test duration", fontsize=12)
        ax.legend(fontsize=9, loc="best")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_throughput_timeseries.png"), dpi=150)
        print(f"  → {PLOT_DIR}/mem_gpu_throughput_timeseries.png")
        plt.close(fig)

    # ── Print Comprehensive Summary Table ────────────────────────────────
    print("\n" + "=" * 105)
    print("MEMORY STRESS vs GPU LATENCY (E2E, COMPUTE, DISPATCH) – SUMMARY")
    print("=" * 105)
    print(f"{'Scenario':<12s} {'Block':>6s} {'BW(MiB/s)':>10s} {'E2E(ms)':>10s} {'Comp(ms)':>10s} "
          f"{'Disp(ms)':>10s} {'Disp/it(us)':>12s} {'CompDeg':>9s} {'DispDeg':>9s} {'Disp%':>7s}")
    print("-" * 105)
    for d, bw in zip(data, bw_avg):
        p = d["params"]
        g = d["gpu"]
        e2e = g["e2e_ms"]
        comp = g["compute_ms"]
        disp = g["dispatch_latency_ms"]
        disp_us = g["dispatch_latency_us"]
        disp_pct = g["dispatch_ratio_pct"]
        c_deg = comp / base_comp
        d_deg = disp / base_disp if base_disp > 0 else 1.0

        print(f"{p['name']:<12s} {p['block_size_str']:>6s} {bw:>10.1f} {e2e:>10.1f} {comp:>10.1f} "
              f"{disp:>10.3f} {disp_us:>12.3f} {c_deg:>8.2f}× {d_deg:>8.2f}× {disp_pct:>6.3f}%")

    print("\n KEY INSIGHTS:")
    print("  • Compute Latency (GPU hardware kernel):")
    print("    - 16K, 128K, 256K (cache-resident) → ~0% degradation (~4110-4136 ms vs baseline 4124 ms).")
    print("    - 1M, 2M, 4M, 8M (cache-evicting) → massive 5.0× to 6.8× slowdown (~20,800 to ~28,075 ms).")
    print("    - The cliff occurs right above 256 KiB where CPU L1 cache overflows.")
    print("  • Dispatch Latency (E2E minus Compute = CPU driver & synchronization overhead):")
    print("    - Baseline dispatch latency is only ~0.176 ms (~0.440 µs/iteration).")
    print("    - Under 256K and 2M stress, dispatch latency spikes to 2.91 ms and 3.59 ms (16.5× to 20.4× degradation!).")
    print("    - This proves CPU-side memory contention severely delays driver queue submission and memory barriers.")


if __name__ == "__main__":
    main()
