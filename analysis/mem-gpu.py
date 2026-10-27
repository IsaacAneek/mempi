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
import numpy as np
import pandas as pd
import glob
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error, r2_score

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
    "font.size": 10,
})

CAT_PALETTE = {
    "baseline": "#4CAF50",         # Green
    "cpu_side": "#795548",         # Brown
    "pagefault": "#607D8B",        # Blue Grey
    "cache_resident": "#2196F3",   # Blue
    "l2_l3_resident": "#FF9800",   # Orange
    "cache_evict": "#F44336",      # Red
    "dram_stream": "#D32F2F",      # Crimson
    "dram_random": "#9C27B0",      # Purple
    "coherence": "#00BCD4",        # Cyan
    "thread_sweep": "#E91E63",     # Pink
}

CAT_SORT_ORDER = {
    "baseline": 0,
    "cpu_side": 1,
    "pagefault": 2,
    "coherence": 3,
    "cache_resident": 4,
    "l2_l3_resident": 5,
    "cache_evict": 6,
    "dram_stream": 7,
    "dram_random": 8,
    "thread_sweep": 9,
}


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
    p = d["params"]
    cat_rank = CAT_SORT_ORDER.get(p.get("category"), 99)
    block_b = p.get("footprint_bytes", 0) or p.get("block_bytes", 0)
    name = p.get("name", "")
    return (cat_rank, block_b, name)

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

    # Sort deterministically: all scenarios included!
    data.sort(key=sort_key)

    labels = [scenario_label(d["params"]) for d in data]
    names = [d["params"]["name"] for d in data]
    colors = [scenario_color(d["params"]) for d in data]

    # Find baseline metrics
    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 4120.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    e2e_vals = [d["gpu"]["e2e_ms"] for d in data]
    comp_vals = [d["gpu"]["compute_ms"] for d in data]
    disp_vals = [d["gpu"]["e2e_minus_gpu_ms"] for d in data]
    disp_us_vals = [d["gpu"]["e2e_minus_gpu_us"] for d in data]
    disp_pct_vals = [d["gpu"]["e2e_minus_gpu_pct"] for d in data]

    x = np.arange(len(data))
    bar_w = 0.38

    # ── Plot 1: Absolute Latency Breakdown (EVERY Scenario) ──────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    # Left: E2E and Compute Latency (ms)
    b1 = ax1.bar(x - bar_w / 2, e2e_vals, bar_w, label="End-to-End Latency",
                 color=colors, edgecolor="black", linewidth=0.6)
    b2 = ax1.bar(x + bar_w / 2, comp_vals, bar_w, label="Compute Latency (GPU elapsed)",
                 color=colors, edgecolor="black", linewidth=0.6, alpha=0.6)

    for bar, val in zip(b1, e2e_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax1.set_xlabel("Interference Scenario (All Parameters)")
    ax1.set_ylabel("Latency (ms)")
    ax1.set_title("E2E vs Compute Latency Across All Scenarios\n(Scale: thousands of ms / seconds)", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")
    ax1.legend(loc="upper left")
    ax1.axhline(base_e2e, color="green", linestyle="--", alpha=0.5, linewidth=1, label=f"Baseline: {base_e2e:.0f} ms")

    # Right: E2E-GPU Residual = E2E - GPU timer (ms and us per dispatch)
    b3 = ax2.bar(x, disp_vals, bar_w * 1.5, color=colors, edgecolor="black", linewidth=0.6)
    for bar, val, val_us in zip(b3, disp_vals, disp_us_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                 f"{val:.3f} ms\n({val_us:.1f} µs)", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax2.set_xlabel("Interference Scenario (All Parameters)")
    ax2.set_ylabel("E2E-GPU Residual (ms) = E2E - GPU timer")
    ax2.set_title("E2E - GPU timer (signed residual; NOT a pure CPU dispatch cost)\n(Scale: fractions of ms / microseconds)", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")
    ax2.axhline(base_disp, color="green", linestyle="--", alpha=0.5, linewidth=1, label=f"Baseline: {base_disp:.3f} ms")
    ax2.legend(loc="upper left")

    fig.suptitle("GPU Task Latency Breakdown: Compute vs E2E-GPU Residual Across EVERY Parameter",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_absolute_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_absolute_latency.png")
    plt.close(fig)

    # ── Plot 2: Degradation Factor Comparison (EVERY Scenario) ───────────
    degr_e2e = [v / base_e2e for v in e2e_vals]
    degr_comp = [v / base_comp for v in comp_vals]
    degr_disp = [v / base_disp for v in disp_vals]

    fig, ax = plt.subplots(figsize=(16, 6.5))
    w3 = 0.26
    b_e2e = ax.bar(x - w3, degr_e2e, w3, label="E2E Degradation (×)", color="#42A5F5", edgecolor="black", linewidth=0.5)
    b_cmp = ax.bar(x, degr_comp, w3, label="Compute Degradation (×)", color="#EF5350", edgecolor="black", linewidth=0.5)
    b_dsp = ax.bar(x + w3, degr_disp, w3, label="Residual Ratio (×) [E2E - GPU timer]", color="#FFA726", edgecolor="black", linewidth=0.5)

    for bar, val in zip(b_e2e, degr_e2e):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15, f"{val:.1f}×", ha="center", fontsize=7)
    for bar, val in zip(b_cmp, degr_comp):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15, f"{val:.1f}×", ha="center", fontsize=7)
    for bar, val in zip(b_dsp, degr_disp):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15, f"{val:.1f}×", ha="center", fontsize=7, fontweight="bold", color="#D84315")

    ax.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.7, label="1.0× Baseline")
    ax.set_xlabel("Interference Scenario (All Parameters)")
    ax.set_ylabel("Degradation Factor (× Baseline)")
    ax.set_title("Latency Degradation Comparison Across All Parameters: E2E vs Compute vs E2E-GPU Residual",
                 fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")
    ax.legend(loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_degradation_comparison.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_degradation_comparison.png")
    plt.close(fig)

    # ── Plot 3: E2E-GPU Residual vs Compute Latency & Ratio (EVERY Scenario) ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    # Left: Dual-Axis Compute Latency vs E2E-GPU Residual across all scenarios
    ax1_twin = ax1.twinx()
    p1 = ax1.bar(x, comp_vals, bar_w * 1.5, color=colors, edgecolor="black", linewidth=0.6,
                 label="Compute Latency (ms)")
    p2 = ax1_twin.plot(x, disp_vals, "o--", color="#D84315", markersize=6.5, linewidth=1.8,
                       label="E2E-GPU Residual (ms)")

    for bar, val in zip(p1, comp_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    for i, val in enumerate(disp_vals):
        ax1_twin.text(i, val + 0.08, f"{val:.2f}", ha="center", va="bottom",
                      fontsize=7, fontweight="bold", color="#D84315")

    ax1.set_xlabel("Interference Scenario (All Parameters)")
    ax1.set_ylabel("Compute Latency (ms)", color="black")
    ax1_twin.set_ylabel("E2E-GPU Residual (ms) = E2E - GPU timer", color="#D84315")
    ax1.set_title("Compute Latency vs E2E-GPU Residual Across All Scenarios", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")

    # Combined legend
    lines = [p1, p2[0]]
    leg_labels = [l.get_label() for l in lines]
    ax1.legend(lines, leg_labels, loc="upper left", fontsize=8.5)

    # Right: E2E-GPU Residual as % of Total E2E Latency
    bars_pct = ax2.bar(x, disp_pct_vals, bar_w * 1.5, color=colors, edgecolor="black", linewidth=0.5)
    for bar, val in zip(bars_pct, disp_pct_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.001,
                 f"{val:.3f}%", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax2.set_xlabel("Interference Scenario (All Parameters)")
    ax2.set_ylabel("E2E-GPU Residual (% of E2E Latency)")
    ax2.set_title("E2E-GPU Residual Proportion of Total Execution Time", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")

    fig.suptitle("E2E-GPU Residual & GPU Compute Latency Comparison Across All Scenarios", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_residual_vs_compute.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_residual_vs_compute.png")
    plt.close(fig)

    # ── Plot 4: Latencies Across ALL Scenarios & Hierarchy (NO FILTERING!) ─
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6))

    # Left: All Scenarios Compute & E2E-GPU Residual Side-by-Side
    ax1_twin = ax1.twinx()
    p1 = ax1.bar(x - bar_w / 2, comp_vals, bar_w, color=colors, edgecolor="black", label="Compute Latency (ms)")
    p2 = ax1_twin.plot(x + bar_w / 2, disp_vals, "s--", color="black", markersize=6, linewidth=1.5, label="E2E-GPU Residual (ms)")

    ax1.set_xlabel("Interference Scenario (All Parameters)")
    ax1.set_ylabel("Compute Latency (ms)", color="black")
    ax1_twin.set_ylabel("E2E-GPU Residual (ms)", color="black")
    ax1.set_title("All Scenarios: Compute & E2E-GPU Residuals\n(Includes CPU-side, Pagefaults, Cache, DRAM)", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")

    # Right: Memory Block Size Scaling + CPU-Side Reference Overlay
    stress_mem = [d for d in data if d["params"]["footprint_bytes"] > 0]
    if stress_mem:
        b_kib = [d["params"]["footprint_bytes"] / 1024.0 for d in stress_mem]   # aggregate = block x threads
        b_comp = [d["gpu"]["compute_ms"] for d in stress_mem]
        b_disp = [d["gpu"]["e2e_minus_gpu_ms"] for d in stress_mem]

        ax2_twin = ax2.twinx()
        ax2.plot(b_kib, b_comp, "ro-", linewidth=2.0, markersize=7, label="Memory: Compute (ms)")
        ax2_twin.plot(b_kib, b_disp, "bs--", linewidth=1.8, markersize=7, label="Memory: Residual (ms)")

        # OVERLAY ALL NON-MEMORY SCENARIOS as horizontal reference lines / markers
        non_mem = [d for d in data if d["params"]["footprint_bytes"] == 0 and d["params"]["name"] != "baseline"]
        overlay_colors = ["#795548", "#607D8B", "#FF5722", "#4CAF50"]
        for idx, nm in enumerate(non_mem):
            col = overlay_colors[idx % len(overlay_colors)]
            nm_comp = nm["gpu"]["compute_ms"]
            nm_name = nm["params"]["name"]
            ax2.axhline(nm_comp, color=col, linestyle=":", alpha=0.8,
                        label=f"{nm_name} Compute: {nm_comp:.0f}ms")

        # Documented BCM2712 / Cortex-A76 sizes (hypotheses until verified on the device)
        ax2.axvline(64, color="purple", linestyle=":", alpha=0.7, label="L1D per core (64 KiB)")
        ax2.axvline(512, color="teal", linestyle=":", alpha=0.7, label="L2 per core (512 KiB)")
        ax2.axvline(2048, color="brown", linestyle=":", alpha=0.7, label="L3 shared (2 MiB)")

        ax2.set_xscale("log", base=2)
        ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda val, pos: f"{int(val)}K" if val < 1024 else f"{int(val/1024)}M"))
        ax2.set_xlabel("Aggregate working set = block x threads (log scale)")
        ax2.set_ylabel("Compute Latency (ms)", color="red")
        ax2_twin.set_ylabel("E2E-GPU Residual (ms)", color="blue")
        ax2.set_title("Aggregate Working-Set Progression with CPU-Side Contention Reference", fontsize=11)
        ax2.legend(loc="upper left", fontsize=7.5)

    fig.suptitle("Comprehensive Latency Scaling Across Memory, CPU, and OS Interference", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "mem_gpu_blocksize_vs_latencies.png"), dpi=150)
    print(f"  → {PLOT_DIR}/mem_gpu_blocksize_vs_latencies.png")
    plt.close(fig)

    # ── Plot 5: Bandwidth Consumed vs Latencies (EVERY Scenario) ──────────
    bw_avg = []
    for d in data:
        tp = d["sysbench_throughput"]
        if not tp.empty:
            bw_avg.append(tp["mib_per_sec"].mean())
        else:
            bw_avg.append(0.0)

    fig, ax1 = plt.subplots(figsize=(15, 6))
    ax2 = ax1.twinx()

    bar_bw = ax1.bar(x, bw_avg, bar_w * 1.4, color="#90CAF9", edgecolor="black",
                     linewidth=0.5, alpha=0.8, label="DRAM Bandwidth (MiB/s)")
    line_comp = ax2.plot(x, comp_vals, "ro-", markersize=7, linewidth=2, label="Compute Latency (ms)")
    line_disp = ax2.plot(x, [v * 1000 for v in disp_vals], "gs--", markersize=6, linewidth=1.5, label="E2E-GPU Residual (×1000 ms)")

    ax1.set_xlabel("Interference Scenario (All Parameters)")
    ax1.set_ylabel("DRAM Bandwidth Generated (MiB/s)", color="#1565C0")
    ax2.set_ylabel("Latency (ms / ×1000)", color="black")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=7.5, rotation=25, ha="right")

    # Annotate CPU-side and pagefault scenarios that generate 0 DRAM BW
    for i, (b, d) in enumerate(zip(bw_avg, data)):
        p = d["params"]
        if b == 0.0 and p["name"] != "baseline":
            ax1.text(i, 2000, f"0 MiB/s\n({p['category']})", ha="center", va="bottom",
                     fontsize=7, color="#5D4037", fontweight="bold")

    lines_all = [bar_bw, line_comp[0], line_disp[0]]
    labels_all = ["DRAM Bandwidth (MiB/s)", "Compute Latency (ms)", "E2E-GPU Residual × 1000 (ms)"]
    ax1.legend(lines_all, labels_all, loc="upper left", fontsize=8.5)
    ax1.set_title("Interference Bandwidth vs Compute & E2E-GPU Residual Across ALL Parameters", fontsize=12)
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
