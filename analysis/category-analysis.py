#!/usr/bin/env python3
"""
category-analysis.py  ─  Comprehensive Multi-Category Interference Analysis
=============================================================================
Analyzes and visualizes specialized interference parameter categories:

1. COHERENCE (e.g. 32kw_t2_g, 256kw_g):
   Shared buffer (scope=global, _g) vs private buffer (scope=local).
   Isolates core-to-core cache-line ping-ponging / MESI invalidations.

2. THREAD SWEEP (e.g. 4mr_t1, 4mr_t2, 4mr, 64mw_t8):
   Bandwidth intensity & latency degradation scaling across thread counts (1, 2, 4, 8, 16).

3. CPU-SIDE CONTENTION (e.g. 32kn, cpu_prime_t8, mutex1_t4, threads_t16):
   Pure CPU computation, lock contention, and scheduler context-switching
   WITHOUT memory-bandwidth pressure (contrasting CPU load vs DRAM contention).

4. PAGE FAULTS (e.g. pf_64mw_t4, ng_fault_t4):
   Repeated mmap first-touch faults and OS page-table traps vs streaming memory.

5. CROSS-CATEGORY BENCHMARK COMPARISON:
   High-level comparison across all 9 experimental categories.

Plots generated (saved to analysis/plots/):
  - category_cross_comparison.png: All categories latency & degradation overview.
  - category_coherence.png: Local vs Global buffer comparison (cache bouncing penalty).
  - category_thread_sweep.png: Thread count scaling vs latency & bandwidth.
  - category_cpu_side_vs_dram.png: CPU compute/mutex load vs DRAM streaming.
  - category_pagefault_impact.png: Page fault impact on compute vs dispatch latency.
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

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f8f8",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
})

CAT_PALETTE = {
    "baseline": "#4CAF50",         # Green
    "cache_resident": "#2196F3",   # Blue
    "cache_evict": "#FF9800",      # Orange
    "dram_stream": "#F44336",      # Red
    "dram_random": "#9C27B0",      # Purple
    "coherence": "#00BCD4",        # Cyan
    "thread_sweep": "#E91E63",     # Pink
    "cpu_side": "#795548",         # Brown
    "pagefault": "#607D8B",        # Blue Grey
}


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["dispatch_latency_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    # Group scenarios by category
    by_cat = {}
    for d in data:
        cat = d["params"]["category"]
        by_cat.setdefault(cat, []).append(d)

    print("\n" + "=" * 90)
    print("CATEGORIES DETECTED IN DATA:")
    for cat, items in sorted(by_cat.items()):
        names = [d["params"]["name"] for d in items]
        print(f"  • {cat:<15s}: {len(items):>2d} scenarios ({', '.join(names[:6])}{'...' if len(names) > 6 else ''})")
    print("=" * 90)

    # ── Plot 1: Cross-Category Benchmark Overview ────────────────────────
    # For every category present, compute average Compute and Dispatch latency
    cat_names = []
    cat_comp_avg = []
    cat_disp_avg = []
    cat_comp_deg = []
    cat_disp_deg = []
    cat_colors = []

    # Desired order
    order = ["baseline", "cpu_side", "cache_resident", "cache_evict", "dram_stream", "dram_random", "coherence", "thread_sweep", "pagefault"]
    for c in order:
        if c in by_cat:
            cat_names.append(c.replace("_", "\n"))
            c_comp = np.mean([d["gpu"]["compute_ms"] for d in by_cat[c]])
            c_disp = np.mean([d["gpu"]["dispatch_latency_ms"] for d in by_cat[c]])
            cat_comp_avg.append(c_comp)
            cat_disp_avg.append(c_disp)
            cat_comp_deg.append(c_comp / base_comp)
            cat_disp_deg.append(c_disp / base_disp)
            cat_colors.append(CAT_PALETTE.get(c, "#9E9E9E"))

    # Also include any categories not in standard list
    for c in by_cat:
        if c not in order:
            cat_names.append(c.replace("_", "\n"))
            c_comp = np.mean([d["gpu"]["compute_ms"] for d in by_cat[c]])
            c_disp = np.mean([d["gpu"]["dispatch_latency_ms"] for d in by_cat[c]])
            cat_comp_avg.append(c_comp)
            cat_disp_avg.append(c_disp)
            cat_comp_deg.append(c_comp / base_comp)
            cat_disp_deg.append(c_disp / base_disp)
            cat_colors.append(CAT_PALETTE.get(c, "#9E9E9E"))

    x_cat = np.arange(len(cat_names))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Left: Compute Degradation by Category
    b1 = ax1.bar(x_cat, cat_comp_deg, color=cat_colors, edgecolor="black", linewidth=0.6)
    ax1.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.8, label="1.0× Baseline")
    for bar, val in zip(b1, cat_comp_deg):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15,
                 f"{val:.2f}×", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax1.set_ylabel("Compute Degradation Factor (× baseline)")
    ax1.set_title("GPU Compute Kernel Degradation by Category\n(DRAM streaming/random vs CPU/cache resident)", fontsize=12)
    ax1.set_xticks(x_cat)
    ax1.set_xticklabels(cat_names, fontsize=8)
    ax1.legend(loc="upper left")

    # Right: Dispatch Degradation by Category
    b2 = ax2.bar(x_cat, cat_disp_deg, color=cat_colors, edgecolor="black", linewidth=0.6)
    ax2.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.8, label="1.0× Baseline")
    for bar, val in zip(b2, cat_disp_deg):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f}×", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax2.set_ylabel("Dispatch Degradation Factor (× baseline)")
    ax2.set_title("CPU Dispatch Overhead Degradation by Category\n(E2E minus Compute: driver & queue flushes)", fontsize=12)
    ax2.set_xticks(x_cat)
    ax2.set_xticklabels(cat_names, fontsize=8)
    ax2.legend(loc="upper left")

    fig.suptitle("Interference Profile Across All Experimental Categories", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_cross_comparison.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_cross_comparison.png")
    plt.close(fig)

    # ── Plot 2: CPU-Side Contention vs DRAM Pressure ─────────────────────
    # Compare cpu_side scenarios (mutex, prime, threads) vs baseline vs DRAM stream
    cpu_side_items = by_cat.get("cpu_side", [])
    dram_items = by_cat.get("dram_stream", []) + by_cat.get("dram_random", [])
    cache_items = by_cat.get("cache_resident", [])

    comp_set = []
    if baseline:
        comp_set.append(baseline)
    comp_set.extend(cpu_side_items)
    if cache_items:
        comp_set.append(cache_items[0])
    if dram_items:
        comp_set.append(dram_items[0])
    if len(dram_items) > 1:
        comp_set.append(dram_items[1])

    if len(comp_set) > 1:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        x_cs = np.arange(len(comp_set))
        cs_labels = [d["params"]["name"] for d in comp_set]
        cs_colors = [CAT_PALETTE.get(d["params"]["category"], "#9E9E9E") for d in comp_set]
        cs_comp = [d["gpu"]["compute_ms"] for d in comp_set]
        cs_disp = [d["gpu"]["dispatch_latency_ms"] for d in comp_set]

        b_c = ax1.bar(x_cs, cs_comp, color=cs_colors, edgecolor="black", linewidth=0.6)
        for bar, val in zip(b_c, cs_comp):
            deg = val / base_comp
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 400,
                     f"{val:.0f} ms\n({deg:.2f}×)", ha="center", va="bottom", fontsize=8, fontweight="bold")

        ax1.set_ylabel("Compute Latency (ms)")
        ax1.set_title("Compute Latency: CPU Contention vs DRAM Contention\n(Pure CPU load does NOT degrade GPU compute!)", fontsize=11)
        ax1.set_xticks(x_cs)
        ax1.set_xticklabels(cs_labels, fontsize=8, rotation=20, ha="right")

        b_d = ax2.bar(x_cs, cs_disp, color=cs_colors, edgecolor="black", linewidth=0.6)
        for bar, val in zip(b_d, cs_disp):
            deg = val / base_disp
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                     f"{val:.3f} ms\n({deg:.1f}×)", ha="center", va="bottom", fontsize=8, fontweight="bold")

        ax2.set_ylabel("Dispatch Latency (ms)")
        ax2.set_title("Dispatch Latency: CPU Contention vs DRAM Contention\n(CPU lock contention delays dispatch submission)", fontsize=11)
        ax2.set_xticks(x_cs)
        ax2.set_xticklabels(cs_labels, fontsize=8, rotation=20, ha="right")

        fig.suptitle("CPU-Side Load (Mutex / Prime / Threads) vs Memory Bandwidth Contention", fontsize=13, fontweight="bold")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "category_cpu_side_vs_dram.png"), dpi=150)
        print(f"  → {PLOT_DIR}/category_cpu_side_vs_dram.png")
        plt.close(fig)

    # ── Plot 3: Page Faults Impact ───────────────────────────────────────
    pf_items = by_cat.get("pagefault", [])
    if pf_items:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
        pf_set = []
        if baseline:
            pf_set.append(baseline)
        pf_set.extend(pf_items)
        if cache_items:
            pf_set.append(cache_items[0])
        if dram_items:
            pf_set.append(dram_items[0])

        x_pf = np.arange(len(pf_set))
        pf_labels = [d["params"]["name"] for d in pf_set]
        pf_colors = [CAT_PALETTE.get(d["params"]["category"], "#9E9E9E") for d in pf_set]
        pf_comp = [d["gpu"]["compute_ms"] for d in pf_set]
        pf_disp = [d["gpu"]["dispatch_latency_ms"] for d in pf_set]

        b1 = ax1.bar(x_pf, pf_comp, color=pf_colors, edgecolor="black", linewidth=0.6)
        for bar, val in zip(b1, pf_comp):
            deg = val / base_comp
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                     f"{val:.0f} ms\n({deg:.2f}×)", ha="center", va="bottom", fontsize=8, fontweight="bold")

        ax1.set_ylabel("Compute Latency (ms)")
        ax1.set_title("Page Fault Impact on Compute Latency", fontsize=11)
        ax1.set_xticks(x_pf)
        ax1.set_xticklabels(pf_labels, fontsize=8, rotation=20, ha="right")

        b2 = ax2.bar(x_pf, pf_disp, color=pf_colors, edgecolor="black", linewidth=0.6)
        for bar, val in zip(b2, pf_disp):
            deg = val / base_disp
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                     f"{val:.3f} ms\n({deg:.1f}×)", ha="center", va="bottom", fontsize=8, fontweight="bold")

        ax2.set_ylabel("Dispatch Latency (ms)")
        ax2.set_title("Page Fault Impact on CPU Dispatch Latency", fontsize=11)
        ax2.set_xticks(x_pf)
        ax2.set_xticklabels(pf_labels, fontsize=8, rotation=20, ha="right")

        fig.suptitle("Page Fault Interference (stress-ng fault / mmap) vs GPU Latencies", fontsize=13, fontweight="bold")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "category_pagefault_impact.png"), dpi=150)
        print(f"  → {PLOT_DIR}/category_pagefault_impact.png")
        plt.close(fig)

    # ── Plot 4: Coherence: Scope Global vs Scope Local ───────────────────
    # If coherence scenarios are present, compare _g (global) vs local
    coh_items = by_cat.get("coherence", [])
    if coh_items:
        fig, ax = plt.subplots(figsize=(10, 6))
        # Match global with local if found
        coh_names = [d["params"]["name"] for d in coh_items]
        coh_comp = [d["gpu"]["compute_ms"] for d in coh_items]
        coh_disp = [d["gpu"]["dispatch_latency_ms"] for d in coh_items]
        x_c = np.arange(len(coh_items))

        ax.bar(x_c - 0.2, [c / base_comp for c in coh_comp], 0.35, label="Compute Degradation (×)", color="#00BCD4", edgecolor="black")
        ax.bar(x_c + 0.2, [d / base_disp for d in coh_disp], 0.35, label="Dispatch Degradation (×)", color="#FFA726", edgecolor="black")
        ax.set_xticks(x_c)
        ax.set_xticklabels(coh_names, fontsize=9)
        ax.set_ylabel("Degradation Factor (× baseline)")
        ax.set_title("Cache Coherence Interference: Global Buffer Bouncing Across Cores", fontsize=12)
        ax.legend()
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "category_coherence.png"), dpi=150)
        print(f"  → {PLOT_DIR}/category_coherence.png")
        plt.close(fig)

    # ── Plot 5: Thread Sweep ─────────────────────────────────────────────
    # If thread sweep scenarios are present, plot thread scaling
    ts_items = by_cat.get("thread_sweep", [])
    if ts_items:
        fig, ax1 = plt.subplots(figsize=(10, 6))
        ax2 = ax1.twinx()
        ts_items.sort(key=lambda d: d["params"]["threads"])
        thr_vals = [d["params"]["threads"] for d in ts_items]
        ts_comp = [d["gpu"]["compute_ms"] for d in ts_items]
        ts_disp = [d["gpu"]["dispatch_latency_ms"] for d in ts_items]

        p1 = ax1.plot(thr_vals, [c / base_comp for c in ts_comp], "ro-", label="Compute Degradation (×)", linewidth=2)
        p2 = ax2.plot(thr_vals, [d / base_disp for d in ts_disp], "bs--", label="Dispatch Degradation (×)", linewidth=2)

        ax1.set_xlabel("CPU Thread Count")
        ax1.set_ylabel("Compute Degradation (×)", color="red")
        ax2.set_ylabel("Dispatch Degradation (×)", color="blue")
        ax1.set_title("Thread Count Sweep: Bandwidth Intensity vs GPU Degradation", fontsize=12)
        lines = p1 + p2
        labels = [l.get_label() for l in lines]
        ax1.legend(lines, labels, loc="upper left")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "category_thread_sweep.png"), dpi=150)
        print(f"  → {PLOT_DIR}/category_thread_sweep.png")
        plt.close(fig)

    print("\n Category Analysis completed successfully!")


if __name__ == "__main__":
    main()

