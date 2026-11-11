#!/usr/bin/env python3
"""
mem-gpu.py  ─  Comprehensive Parameter Analysis: Memory Stress & CPU Contention vs GPU Latency
=============================================================================================
Analyzes and visualizes EVERY parameter and interference scenario in the dataset:
  - Baseline (isolated GPU execution)
  - CPU-side contentions (mutex lock contention, prime computation, scheduler thread storms)
  - Page-fault stressors (stress-ng fault/mmap, repeated page table traps)
  - Small-working-set memory workloads (per-thread blocks <= 256K, aggregate <= 2 MiB)
  - Cache-pressure workloads (aggregate block x threads above the 2 MiB L3, e.g. 1M x 4)
  - Large-working-set DRAM streaming & random access (8M+ per thread)
  - Cache coherence (global shared buffer bouncing) & Thread count sweeps

Evaluates:
  1. GPU timer (GL_TIME_ELAPSED_EXT elapsed time of the batch; includes barriers, not pure shader time)
  2. E2E-GPU Residual = End-to-End (E2E) - Compute Latency
  3. Total End-to-End (E2E) Latency

Plots generated (saved to analysis/plots/):
  1. mem_gpu_absolute_latency.png:
     Dual-panel: E2E & Compute Latency (seconds scale) vs E2E-GPU Residual (ms scale) for EVERY scenario.
  2. mem_gpu_degradation_comparison.png:
     Grouped degradation factor (× baseline) comparing E2E, Compute, and E2E-GPU Residual across EVERY scenario.
  3. mem_gpu_residual_vs_compute.png:
     Dual-axis comparison of Compute Latency vs E2E-GPU Residual & Overhead Ratio (% of E2E) across EVERY scenario.
  4. mem_gpu_blocksize_vs_latencies.png:
     Dual-panel: All scenarios latency profile (left) + Block size cache hierarchy progression with CPU-side reference (right).
  5. mem_gpu_bandwidth_vs_latency.png:
     Sysbench memory bandwidth vs Compute and E2E-GPU Residual across EVERY scenario.
  6. mem_gpu_throughput_timeseries.png:
     Memory throughput / activity time-series during GPU execution.
"""

import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import glob
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error, r2_score

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import (
    load_all,
    DATA_DIR,
    CAT_PALETTE,
    CAT_SORT_ORDER,
    pair_sort_key,
    compute_pair_positions,
    split_data_parts,
)

PLOT_DIR = os.path.join(os.path.dirname(__file__), "plots")
os.makedirs(PLOT_DIR, exist_ok=True)

# ── Styling ──────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f8f8",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 10,
})


def scenario_color(params):
    cat = params.get("category", "")
    return CAT_PALETTE.get(cat, "#9E9E9E")


def scenario_label(params):
    name = params["name"]
    cat = params.get("category", "")
    mode = params.get("mode", "")
    if name == "baseline":
        return "Baseline\n(no stress)"
    if cat == "cpu_side":
        if mode == "mutex":
            return f"mutex{params.get('block_str', '1')}\n(t={params.get('threads', 4)})"
        elif mode == "cpu":
            return f"cpu_prime\n(t={params.get('threads', 4)})"
        elif mode == "threads":
            return f"threads_yield\n(t={params.get('threads', 4)})"
        return f"{name}\n(cpu_side)"
    if cat == "pagefault":
        return f"{name}\n(pagefault)"
    if cat == "coherence":
        return f"{params['block_str']} {params['oper']}\n(shared_g)"
    if cat == "thread_sweep":
        return f"{params['block_str']} {params['oper']}\n(t={params['threads']})"

    acc = "rnd" if params.get("access") == "rnd" else "seq"
    block = params.get("block_str", "-")
    oper = params.get("oper", "")
    return f"{block} {oper}\n({acc})"

def sort_key(d):
    return pair_sort_key(d)

def load_all_task_data(base_dir="data"):
    # Dynamically find all task directories (e.g., task1, task2, ..., task10)
    task_dirs = glob.glob(os.path.join(base_dir, "task*"))
    all_data = []

    for t_dir in task_dirs:
        task_name = os.path.basename(t_dir)
        csv_files = glob.glob(os.path.join(t_dir, "*.csv"))
        
        for file in csv_files:
            df = pd.read_csv(file)
            df['task_id'] = task_name  # Tag data with its specific task source
            all_data.append(df)
            
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()

def evaluate_models(X_train, X_test, y_train, y_test):
    models = {
        "Random Forest": RandomForestRegressor(n_estimators=100, random_state=42),
        "Gradient Boosting": GradientBoostingRegressor(random_state=42),
        "Ridge Linear": Ridge(alpha=1.0),
        "SVR": SVR(kernel='rbf')
    }

    results = {}
    for name, model in models.items():
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)

        r2 = r2_score(y_test, predictions)
        rmse = np.sqrt(mean_squared_error(y_test, predictions))

        results[name] = {"R2": r2, "RMSE": rmse}
        print(f"[{name}] -> R2: {r2:.4f} | RMSE: {rmse:.4f}")

    return results


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    # Sort deterministically: all scenarios included, with read/write counterpart pairs consecutive!
    data.sort(key=pair_sort_key)

    # Split data into Part 1 (CPU & Cache <= 4 MiB) and Part 2 (DRAM, Sweeps, System >= 8 MiB)
    data_p1, data_p2 = split_data_parts(data)

    bar_w = 0.38
    x1, ticks1, labels1 = compute_pair_positions(data_p1, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)
    x2, ticks2, labels2 = compute_pair_positions(data_p2, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)

    colors1 = [scenario_color(d["params"]) for d in data_p1]
    colors2 = [scenario_color(d["params"]) for d in data_p2]

    # Find baseline metrics
    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 4120.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    e2e_vals1 = [d["gpu"]["e2e_ms"] for d in data_p1]
    comp_vals1 = [d["gpu"]["compute_ms"] for d in data_p1]
    disp_vals1 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p1]
    disp_pct1 = [d["gpu"]["e2e_minus_gpu_pct"] for d in data_p1]
    degr_comp1 = [v / base_comp for v in comp_vals1]
    degr_disp1 = [v / base_disp for v in disp_vals1]

    e2e_vals2 = [d["gpu"]["e2e_ms"] for d in data_p2]
    comp_vals2 = [d["gpu"]["compute_ms"] for d in data_p2]
    disp_vals2 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p2]
    disp_pct2 = [d["gpu"]["e2e_minus_gpu_pct"] for d in data_p2]
    degr_comp2 = [v / base_comp for v in comp_vals2]
    degr_disp2 = [v / base_disp for v in disp_vals2]

    # Full data metrics (for tables and reference plots)
    e2e_vals = [d["gpu"]["e2e_ms"] for d in data]
    comp_vals = [d["gpu"]["compute_ms"] for d in data]
    disp_vals = [d["gpu"]["e2e_minus_gpu_ms"] for d in data]
    disp_us_vals = [d["gpu"]["e2e_minus_gpu_us"] for d in data]
    disp_pct_vals = [d["gpu"]["e2e_minus_gpu_pct"] for d in data]

    # Legend patches for Read vs Write distinction
    legend_read = Patch(facecolor="#9E9E9E", edgecolor="black", label="Read (solid)")
    legend_write = Patch(facecolor="#9E9E9E", edgecolor="black", hatch="//", label="Write (hatched //)")

    # ── Plot 1: Absolute Latency Breakdown (Split: Part 1 & Part 2) ───────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    ax1_twin = ax1.twinx()
    b1 = ax1.bar(x1, comp_vals1, bar_w, label="Compute Latency", color=colors1, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b1, data_p1, comp_vals1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 150,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    l1_e2e = ax1.plot(x1, e2e_vals1, "k_", markersize=8, markeredgewidth=1.5, label="End-to-End Latency")
    l1_disp = ax1_twin.plot(x1, disp_vals1, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")

    ax1.set_ylabel("Latency (ms)", fontsize=10)
    ax1_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315", fontsize=10)
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.axhline(base_comp, color="green", linestyle="--", alpha=0.6, linewidth=1, label=f"Baseline: {base_comp:.0f} ms")
    lines1 = [b1, l1_e2e[0], l1_disp[0], legend_read, legend_write]
    labels_lg1 = ["Compute Latency", "End-to-End", "E2E-GPU Residual", "Read (solid)", "Write (hatched //)"]
    ax1.legend(lines1, labels_lg1, loc="upper left", fontsize=8)

    # Panel 2: Part 2
    ax2_twin = ax2.twinx()
    b2 = ax2.bar(x2, comp_vals2, bar_w, label="Compute Latency", color=colors2, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b2, data_p2, comp_vals2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 250,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    l2_e2e = ax2.plot(x2, e2e_vals2, "k_", markersize=8, markeredgewidth=1.5, label="End-to-End Latency")
    l2_disp = ax2_twin.plot(x2, disp_vals2, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")

    ax2.set_ylabel("Latency (ms)", fontsize=10)
    ax2_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.axhline(base_comp, color="green", linestyle="--", alpha=0.6, linewidth=1, label=f"Baseline: {base_comp:.0f} ms")
    lines2 = [b2, l2_e2e[0], l2_disp[0], legend_read, legend_write]
    labels_lg2 = ["Compute Latency", "End-to-End", "E2E-GPU Residual", "Read (solid)", "Write (hatched //)"]
    ax2.legend(lines2, labels_lg2, loc="upper left", fontsize=8)

    fig.suptitle("GPU Task Latency Breakdown: Compute vs E2E-GPU Residual (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_absolute_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_absolute_latency.png")
    plt.close(fig)

    # ── Plot 2: Degradation Factor Comparison (Split: Part 1 & Part 2) ───────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    ax1_twin = ax1.twinx()
    b_cmp1 = ax1.bar(x1, degr_comp1, bar_w, color=colors1, edgecolor="black", linewidth=0.6, label="Compute Degradation")
    for bar, d, val in zip(b_cmp1, data_p1, degr_comp1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.08,
                 f"{val:.2f}×", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    l_dsp1 = ax1_twin.plot(x1, degr_disp1, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="Residual Ratio")
    ax1.axhline(1.0, color="green", linestyle="--", linewidth=1.2, label="1.0× Baseline")
    ax1.set_ylabel("Compute Degradation (× baseline)", fontsize=10)
    ax1_twin.set_ylabel("Residual Ratio (× baseline)", color="#D84315", fontsize=10)
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Degradation Multiples", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    lines_deg1 = [b_cmp1, l_dsp1[0], legend_read, legend_write]
    ax1.legend(lines_deg1, ["Compute Degradation", "Residual Ratio", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    # Panel 2: Part 2
    ax2_twin = ax2.twinx()
    b_cmp2 = ax2.bar(x2, degr_comp2, bar_w, color=colors2, edgecolor="black", linewidth=0.6, label="Compute Degradation")
    for bar, d, val in zip(b_cmp2, data_p2, degr_comp2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.08,
                 f"{val:.2f}×", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    l_dsp2 = ax2_twin.plot(x2, degr_disp2, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="Residual Ratio")
    ax2.axhline(1.0, color="green", linestyle="--", linewidth=1.2, label="1.0× Baseline")
    ax2.set_ylabel("Compute Degradation (× baseline)", fontsize=10)
    ax2_twin.set_ylabel("Residual Ratio (× baseline)", color="#D84315", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — Degradation Multiples", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    lines_deg2 = [b_cmp2, l_dsp2[0], legend_read, legend_write]
    ax2.legend(lines_deg2, ["Compute Degradation", "Residual Ratio", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    fig.suptitle("Latency Degradation Comparison Across All Parameters (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_degradation_comparison.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_degradation_comparison.png")
    plt.close(fig)

    # ── Plot 3: E2E-GPU Residual vs Compute Latency & Ratio (Split: Part 1 & Part 2) ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    ax1_twin = ax1.twinx()
    p1 = ax1.bar(x1, comp_vals1, bar_w, color=colors1, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d, val in zip(p1, data_p1, comp_vals1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 150,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    p1_pct = ax1_twin.plot(x1, disp_pct1, "o--", color="#D84315", markersize=5.5, linewidth=1.5, label="Residual % of E2E")
    ax1.set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax1_twin.set_ylabel("Residual % of E2E Latency", color="#D84315", fontsize=10)
    ax1.set_title("Part 1: CPU & Cache Scenarios — Compute Latency vs Residual % of Execution Time", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    lines_p3_1 = [p1, p1_pct[0], legend_read, legend_write]
    ax1.legend(lines_p3_1, ["Compute Latency (ms)", "Residual % of E2E", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    # Panel 2: Part 2
    ax2_twin = ax2.twinx()
    p2 = ax2.bar(x2, comp_vals2, bar_w, color=colors2, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d, val in zip(p2, data_p2, comp_vals2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 250,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    p2_pct = ax2_twin.plot(x2, disp_pct2, "o--", color="#D84315", markersize=5.5, linewidth=1.5, label="Residual % of E2E")
    ax2.set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax2_twin.set_ylabel("Residual % of E2E Latency", color="#D84315", fontsize=10)
    ax2.set_title("Part 2: DRAM & System Scenarios — Compute Latency vs Residual % of Execution Time", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    lines_p3_2 = [p2, p2_pct[0], legend_read, legend_write]
    ax2.legend(lines_p3_2, ["Compute Latency (ms)", "Residual % of E2E", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    fig.suptitle("E2E-GPU Residual & GPU Compute Latency Comparison (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_residual_vs_compute.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_residual_vs_compute.png")
    plt.close(fig)

    # ── Plot 4: Latencies Across ALL Scenarios & Hierarchy (3-Panel Split) ──
    fig, axes = plt.subplots(3, 1, figsize=(18, 16))

    # Panel 4a: Part 1 Scenarios
    ax4_1_twin = axes[0].twinx()
    p4_1 = axes[0].bar(x1, comp_vals1, bar_w, color=colors1, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d in zip(p4_1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l4_1 = ax4_1_twin.plot(x1, disp_vals1, "s--", color="black", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")
    axes[0].set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax4_1_twin.set_ylabel("E2E-GPU Residual (ms)", color="black", fontsize=10)
    axes[0].set_title("Part 1: CPU-side & Cache Hierarchy Scenarios (Baseline to 4 MiB)", fontsize=11, fontweight="bold")
    axes[0].set_xticks(ticks1)
    axes[0].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    lines_p4a = [p4_1, l4_1[0], legend_read, legend_write]
    axes[0].legend(lines_p4a, ["Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    # Panel 4b: Part 2 Scenarios
    ax4_2_twin = axes[1].twinx()
    p4_2 = axes[1].bar(x2, comp_vals2, bar_w, color=colors2, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d in zip(p4_2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l4_2 = ax4_2_twin.plot(x2, disp_vals2, "s--", color="black", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")
    axes[1].set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax4_2_twin.set_ylabel("E2E-GPU Residual (ms)", color="black", fontsize=10)
    axes[1].set_title("Part 2: DRAM, Concurrency Sweeps, Coherence & Pagefault Scenarios (8 MiB to 256 MiB+)", fontsize=11, fontweight="bold")
    axes[1].set_xticks(ticks2)
    axes[1].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    lines_p4b = [p4_2, l4_2[0], legend_read, legend_write]
    axes[1].legend(lines_p4b, ["Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    # Panel 4c: Memory Working-Set Progression vs Cache Boundaries
    stress_mem = [d for d in data if d["params"]["footprint_bytes"] > 0]
    if stress_mem:
        b_kib = [d["params"]["footprint_bytes"] / 1024.0 for d in stress_mem]
        b_comp = [d["gpu"]["compute_ms"] for d in stress_mem]
        b_disp = [d["gpu"]["e2e_minus_gpu_ms"] for d in stress_mem]

        ax4c_twin = axes[2].twinx()
        axes[2].plot(b_kib, b_comp, "ro-", linewidth=2.0, markersize=7, label="Memory: Compute (ms)")
        ax4c_twin.plot(b_kib, b_disp, "bs--", linewidth=1.8, markersize=7, label="Memory: Residual (ms)")

        axes[2].axvline(64, color="purple", linestyle=":", alpha=0.7, label="L1D per core (64 KiB)")
        axes[2].axvline(512, color="teal", linestyle=":", alpha=0.7, label="L2 per core (512 KiB)")
        axes[2].axvline(2048, color="brown", linestyle=":", alpha=0.7, label="L3 shared (2 MiB)")

        axes[2].set_xscale("log", base=2)
        axes[2].xaxis.set_major_formatter(mticker.FuncFormatter(lambda val, pos: f"{int(val)}K" if val < 1024 else f"{int(val/1024)}M"))
        axes[2].set_xlabel("Aggregate working set = block x threads (log scale)", fontsize=10)
        axes[2].set_ylabel("Compute Latency (ms)", color="red", fontsize=10)
        ax4c_twin.set_ylabel("E2E-GPU Residual (ms)", color="blue", fontsize=10)
        axes[2].set_title("Memory Working-Set Progression Across Cache Hierarchy (64K to 256M)", fontsize=11, fontweight="bold")
        axes[2].legend(loc="upper left", fontsize=8)

    fig.suptitle("Comprehensive Latency Scaling Across Memory, CPU, and OS Interference (3-Panel Hierarchy)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_blocksize_vs_latencies.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_blocksize_vs_latencies.png")
    plt.close(fig)

    # ── Plot 5: Bandwidth Consumed vs Latencies (Split: Part 1 & Part 2) ──────────
    bw_avg1 = [d["sysbench_throughput"]["mib_per_sec"].mean() if not d["sysbench_throughput"].empty else 0.0 for d in data_p1]
    bw_avg2 = [d["sysbench_throughput"]["mib_per_sec"].mean() if not d["sysbench_throughput"].empty else 0.0 for d in data_p2]
    bw_avg = [d["sysbench_throughput"]["mib_per_sec"].mean() if not d["sysbench_throughput"].empty else 0.0 for d in data]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 5a: Part 1
    ax1_twin = ax1.twinx()
    b_bw1 = ax1.bar(x1, bw_avg1, bar_w, color="#90CAF9", edgecolor="black", linewidth=0.5, alpha=0.85, label="DRAM Bandwidth (MiB/s)")
    for bar, d in zip(b_bw1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c1 = ax1_twin.plot(x1, comp_vals1, "ro-", markersize=6, linewidth=1.8, label="Compute Latency (ms)")
    l_d1 = ax1_twin.plot(x1, [v * 1000 for v in disp_vals1], "gs--", markersize=5, linewidth=1.4, label="E2E-GPU Residual ×1000 (ms)")
    ax1.set_ylabel("DRAM Bandwidth Generated (MiB/s)", color="#1565C0", fontsize=10)
    ax1_twin.set_ylabel("Latency (ms / ×1000)", color="black", fontsize=10)
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Bandwidth vs Latency", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    lines_5a = [b_bw1, l_c1[0], l_d1[0], legend_read, legend_write]
    labels_5a = ["DRAM Bandwidth (MiB/s)", "Compute Latency (ms)", "E2E-GPU Residual × 1000 (ms)", "Read (solid)", "Write (hatched //)"]
    ax1.legend(lines_5a, labels_5a, loc="upper left", fontsize=8)

    # Panel 5b: Part 2
    ax2_twin = ax2.twinx()
    b_bw2 = ax2.bar(x2, bw_avg2, bar_w, color="#90CAF9", edgecolor="black", linewidth=0.5, alpha=0.85, label="DRAM Bandwidth (MiB/s)")
    for bar, d in zip(b_bw2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c2 = ax2_twin.plot(x2, comp_vals2, "ro-", markersize=6, linewidth=1.8, label="Compute Latency (ms)")
    l_d2 = ax2_twin.plot(x2, [v * 1000 for v in disp_vals2], "gs--", markersize=5, linewidth=1.4, label="E2E-GPU Residual ×1000 (ms)")
    ax2.set_ylabel("DRAM Bandwidth Generated (MiB/s)", color="#1565C0", fontsize=10)
    ax2_twin.set_ylabel("Latency (ms / ×1000)", color="black", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — Bandwidth vs Latency", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    lines_5b = [b_bw2, l_c2[0], l_d2[0], legend_read, legend_write]
    labels_5b = ["DRAM Bandwidth (MiB/s)", "Compute Latency (ms)", "E2E-GPU Residual × 1000 (ms)", "Read (solid)", "Write (hatched //)"]
    ax2.legend(lines_5b, labels_5b, loc="upper left", fontsize=8)

    fig.suptitle("Interference Bandwidth vs Compute & E2E-GPU Residual Across ALL Parameters (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_bandwidth_vs_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_bandwidth_vs_latency.png")
    plt.close(fig)

    # ── Plot 6: Throughput / Activity Time-Series ─────────────────────────
    active_ts = [d for d in data if not d["sysbench_throughput"].empty]
    if active_ts:
        fig, ax = plt.subplots(figsize=(14, 6))
        for d in active_ts:
            tp = d["sysbench_throughput"]
            lbl = f"{d['params']['name']} ({d['params']['category']})"
            ax.plot(tp["second"], tp["mib_per_sec"], ".-", label=lbl, linewidth=1.4)

        ax.set_xlabel("Time (seconds since stress start)")
        ax.set_ylabel("Throughput (MiB/s)")
        ax.set_title("Stressor Throughput Time-Series During GPU Execution", fontsize=12)
        ax.legend(fontsize=8, loc="best")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_throughput_timeseries.png"), dpi=150)
        print(f"  → {PLOT_DIR}/mem_gpu_throughput_timeseries.png")
        plt.close(fig)

    # ── Print Comprehensive Summary Table (EVERY Scenario) ───────────────
    print("\n" + "=" * 115)
    print("ALL SCENARIOS & PARAMETERS: LATENCY (E2E, COMPUTE, RESIDUAL) – SUMMARY")
    print("=" * 115)
    print(f"{'Scenario':<14s} {'Category':<15s} {'Mode':<8s} {'Block':>6s} {'BW(MiB/s)':>10s} "
          f"{'E2E(ms)':>10s} {'Comp(ms)':>10s} {'Disp(ms)':>10s} {'CompDeg':>9s} {'DispDeg':>9s}")
    print("-" * 115)
    for d, bw in zip(data, bw_avg):
        p = d["params"]
        g = d["gpu"]
        e2e = g["e2e_ms"]
        comp = g["compute_ms"]
        disp = g["e2e_minus_gpu_ms"]
        c_deg = comp / base_comp
        d_deg = disp / base_disp if base_disp > 0 else 1.0

        print(f"{p['name']:<14s} {p['category']:<15s} {p['mode']:<8s} {p['block_str']:>6s} {bw:>10.1f} "
              f"{e2e:>10.1f} {comp:>10.1f} {disp:>10.3f} {c_deg:>8.2f}× {d_deg:>8.2f}×")

    # If --evaluate-models flag is supplied
    if "--evaluate-models" in sys.argv:
        print("\n" + "=" * 80)
        print("RUNNING MULTI-MODEL EVALUATION ON DATASET")
        print("=" * 80)
        dataset_file = os.path.join(os.path.dirname(__file__), "..", "ml", "dataset", "dataset.csv")
        if not os.path.exists(dataset_file):
            dataset_file = os.path.join(os.path.dirname(__file__), "..", "dataset.csv")
        if os.path.exists(dataset_file):
            from sklearn.model_selection import train_test_split
            df = pd.read_csv(dataset_file)
            feature_cols = [c for c in df.columns if c not in ["experiment", "e2e_latency_ms", "slowdown"]]
            X = df[feature_cols]
            y = df["slowdown"]
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            evaluate_models(X_train, X_test, y_train, y_test)
        else:
            print(f"Dataset file {dataset_file} not found.")

    # ── Plot 6: Throughput / Activity Time-Series ─────────────────────────
    active_ts = [d for d in data if not d["sysbench_throughput"].empty]
    if active_ts:
        fig, ax = plt.subplots(figsize=(14, 6))
        for d in active_ts:
            tp = d["sysbench_throughput"]
            lbl = f"{d['params']['name']} ({d['params']['category']})"
            ax.plot(tp["second"], tp["mib_per_sec"], ".-", label=lbl, linewidth=1.4)

        ax.set_xlabel("Time (seconds since stress start)")
        ax.set_ylabel("Throughput (MiB/s)")
        ax.set_title("Stressor Throughput Time-Series During GPU Execution", fontsize=12)
        ax.legend(fontsize=8, loc="best")
        plt.tight_layout()
        fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_throughput_timeseries.png"), dpi=150)
        print(f"  → {PLOT_DIR}/mem_gpu_throughput_timeseries.png")
        plt.close(fig)

    # ── Print Comprehensive Summary Table (EVERY Scenario) ───────────────
    print("\n" + "=" * 115)
    print("ALL SCENARIOS & PARAMETERS: LATENCY (E2E, COMPUTE, RESIDUAL) – SUMMARY")
    print("=" * 115)
    print(f"{'Scenario':<14s} {'Category':<15s} {'Mode':<8s} {'Block':>6s} {'BW(MiB/s)':>10s} "
          f"{'E2E(ms)':>10s} {'Comp(ms)':>10s} {'Disp(ms)':>10s} {'CompDeg':>9s} {'DispDeg':>9s}")
    print("-" * 115)
    for d, bw in zip(data, bw_avg):
        p = d["params"]
        g = d["gpu"]
        e2e = g["e2e_ms"]
        comp = g["compute_ms"]
        disp = g["e2e_minus_gpu_ms"]
        c_deg = comp / base_comp
        d_deg = disp / base_disp if base_disp > 0 else 1.0

        print(f"{p['name']:<14s} {p['category']:<15s} {p['mode']:<8s} {p['block_str']:>6s} {bw:>10.1f} "
              f"{e2e:>10.1f} {comp:>10.1f} {disp:>10.3f} {c_deg:>8.2f}× {d_deg:>8.2f}×")

    # If --evaluate-models flag is supplied
    if "--evaluate-models" in sys.argv:
        print("\n" + "=" * 80)
        print("RUNNING MULTI-MODEL EVALUATION ON DATASET")
        print("=" * 80)
        dataset_file = os.path.join(os.path.dirname(__file__), "..", "ml", "dataset", "dataset.csv")
        if not os.path.exists(dataset_file):
            dataset_file = os.path.join(os.path.dirname(__file__), "..", "dataset.csv")
        if os.path.exists(dataset_file):
            from sklearn.model_selection import train_test_split
            df = pd.read_csv(dataset_file)
            feature_cols = [c for c in df.columns if c not in ["experiment", "e2e_latency_ms", "slowdown"]]
            X = df[feature_cols]
            y = df["slowdown"]
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            evaluate_models(X_train, X_test, y_train, y_test)
        else:
            print(f"Dataset file {dataset_file} not found.")


if __name__ == "__main__":
    main()
