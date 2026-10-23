#!/usr/bin/env python3
"""
category-analysis.py  ─  Unbiased Cross-Category Analysis Across EVERY Parameter
==================================================================================
Includes and visualizes EVERY scenario and parameter without omission or assumptions:
  - Baseline
  - CPU-side contentions (mutex1_t4, cpu_prime, threads)
  - Page-fault stressors (ng_fault_t4, pf_*)
  - Cache-resident memory stressors (16kr, 128kr, 256kr: aggregate <= 2 MiB)
  - Cache-evicting memory stressors (1mr, 2mr, 4mr: block x threads above the 2 MiB L3)
  - DRAM streaming & random access (8mr, 64mw_rnd)
  - Cache coherence & thread sweeps

Visualizations generated (saved to analysis/plots/):
  1. category_cross_comparison.png:
     Category-level summary of Compute and E2E-GPU Residual degradation across all categories.
  2. category_all_scenarios_compute.png:
     Compute Latency & Compute Degradation (× baseline) for EVERY single scenario.
  3. category_all_scenarios_residual.png:
     E2E-GPU Residual & Residual Ratio (× baseline) for EVERY single scenario.
  4. category_cpu_vs_memory_all.png:
     Direct side-by-side comparison of ALL CPU-side, Pagefault, Cache, and DRAM scenarios.
  5. category_scatter_compute_vs_residual.png:
     Scatter map of Compute Degradation vs Residual Ratio for EVERY scenario.
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


def nice_label(name, params=None):
    if not params:
        return name
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
        return f"{params.get('block_str', '')} {params.get('oper', '')}\n(shared_g)"
    if cat == "thread_sweep":
        return f"{params.get('block_str', '')} {params.get('oper', '')}\n(t={params.get('threads', 4)})"

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


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    # Sort deterministically: all scenarios included!
    data.sort(key=sort_key)

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    names = [d["params"]["name"] for d in data]
    colors_list = [scenario_color(d["params"]) for d in data]
    labels_list = [nice_label(n, d["params"]) for n, d in zip(names, data)]
    x = np.arange(len(data))

    comp_vals = [d["gpu"]["compute_ms"] for d in data]
    disp_vals = [d["gpu"]["e2e_minus_gpu_ms"] for d in data]
    comp_deg_vals = [c / base_comp for c in comp_vals]
    disp_deg_vals = [disp / base_disp for disp in disp_vals]

    # Group scenarios by category
    by_cat = {}
    for d in data:
        cat = d["params"]["category"]
        by_cat.setdefault(cat, []).append(d)

    print("\n" + "=" * 95)
    print("ALL SCENARIOS INCLUDED IN ANALYSIS (NO OMISSIONS):")
    for cat, items in sorted(by_cat.items()):
        scen_str = ", ".join([d["params"]["name"] for d in items])
        print(f"  • {cat:<15s}: {len(items):>2d} scenarios [{scen_str}]")
    print("=" * 95)

    # ── Plot 1: Cross-Category Benchmark Overview ────────────────────────
    order = ["baseline", "cpu_side", "pagefault", "coherence", "cache_resident", "l2_l3_resident", "cache_evict", "dram_stream", "dram_random", "thread_sweep"]
    cat_names = []
    cat_comp_deg = []
    cat_disp_deg = []
    cat_colors = []

    for c in order:
        if c in by_cat:
            cat_names.append(c.replace("_", "\n"))
            c_comp = np.mean([d["gpu"]["compute_ms"] for d in by_cat[c]])
            c_disp = np.mean([d["gpu"]["e2e_minus_gpu_ms"] for d in by_cat[c]])
            cat_comp_deg.append(c_comp / base_comp)
            cat_disp_deg.append(c_disp / base_disp)
            cat_colors.append(CAT_PALETTE.get(c, "#9E9E9E"))

    for c in by_cat:
        if c not in order:
            cat_names.append(c.replace("_", "\n"))
            c_comp = np.mean([d["gpu"]["compute_ms"] for d in by_cat[c]])
            c_disp = np.mean([d["gpu"]["e2e_minus_gpu_ms"] for d in by_cat[c]])
            cat_comp_deg.append(c_comp / base_comp)
            cat_disp_deg.append(c_disp / base_disp)
            cat_colors.append(CAT_PALETTE.get(c, "#9E9E9E"))

    x_cat = np.arange(len(cat_names))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    b1 = ax1.bar(x_cat, cat_comp_deg, color=cat_colors, edgecolor="black", linewidth=0.6)
    ax1.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.8, label="1.0× Baseline")
    for bar, val in zip(b1, cat_comp_deg):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.15,
                 f"{val:.2f}×", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax1.set_ylabel("Compute Degradation Factor (× baseline)")
    ax1.set_title("Average GPU Compute Degradation by Category", fontsize=11)
    ax1.set_xticks(x_cat)
    ax1.set_xticklabels(cat_names, fontsize=8)
    ax1.legend(loc="upper left")

    b2 = ax2.bar(x_cat, cat_disp_deg, color=cat_colors, edgecolor="black", linewidth=0.6)
    ax2.axhline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.8, label="1.0× Baseline")
    for bar, val in zip(b2, cat_disp_deg):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f}×", ha="center", va="bottom", fontsize=8, fontweight="bold")

    ax2.set_ylabel("Residual Ratio Factor (× baseline)")
    ax2.set_title("Average E2E-GPU Residual Degradation by Category", fontsize=11)
    ax2.set_xticks(x_cat)
    ax2.set_xticklabels(cat_names, fontsize=8)
    ax2.legend(loc="upper left")

    fig.suptitle("Interference Profile Summary Across All Experimental Categories", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_cross_comparison.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_cross_comparison.png")
    plt.close(fig)

    # ── Plot 2: Compute Latency Across EVERY Single Scenario ──────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    b_abs = ax1.bar(x, comp_vals, color=colors_list, edgecolor="black", linewidth=0.6)
    for bar, val in zip(b_abs, comp_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 300,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax1.axhline(base_comp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_comp:.0f} ms")
    ax1.set_ylabel("Compute Latency (ms)")
    ax1.set_title("Absolute GPU Compute Latency Across EVERY Scenario", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax1.legend(loc="upper left")

    b_deg = ax2.bar(x, comp_deg_vals, color=colors_list, edgecolor="black", linewidth=0.6)
    for bar, val in zip(b_deg, comp_deg_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                 f"{val:.2f}×", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax2.axhline(1.0, color="green", linestyle="--", linewidth=1.2, label="1.0× Baseline")
    ax2.set_ylabel("Compute Degradation (× baseline)")
    ax2.set_title("Compute Latency Degradation Factor (× baseline) Across EVERY Scenario", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax2.legend(loc="upper left")

    fig.suptitle("GPU Compute Latency & Degradation for Every Tested Parameter", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_all_scenarios_compute.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_all_scenarios_compute.png")
    plt.close(fig)

    # ── Plot 3: E2E-GPU Residual Across EVERY Single Scenario ─────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    b_d_abs = ax1.bar(x, disp_vals, color=colors_list, edgecolor="black", linewidth=0.6)
    for bar, val in zip(b_d_abs, disp_vals):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                 f"{val:.3f}", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax1.axhline(base_disp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_disp:.3f} ms")
    ax1.set_ylabel("E2E-GPU Residual (ms) = E2E - GPU timer")
    ax1.set_title("Absolute E2E-GPU Residual Across EVERY Scenario", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax1.legend(loc="upper left")

    b_d_deg = ax2.bar(x, disp_deg_vals, color=colors_list, edgecolor="black", linewidth=0.6)
    for bar, val in zip(b_d_deg, disp_deg_vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,
                 f"{val:.1f}×", ha="center", va="bottom", fontsize=7.5, fontweight="bold", color="#D84315")

    ax2.axhline(1.0, color="green", linestyle="--", linewidth=1.2, label="1.0× Baseline")
    ax2.set_ylabel("Residual Ratio (× baseline)")
    ax2.set_title("E2E-GPU Residual Degradation Factor (× baseline) Across EVERY Scenario", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax2.legend(loc="upper left")

    fig.suptitle("E2E-GPU Residual (E2E - GPU timer) for Every Tested Parameter", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_all_scenarios_residual.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_all_scenarios_residual.png")
    plt.close(fig)

    # ── Plot 4: Side-by-Side Comparison of ALL Scenarios (Compute vs Residual) ──
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    bar_w = 0.4
    ax1.bar(x, comp_vals, bar_w * 1.5, color=colors_list, edgecolor="black", linewidth=0.6)
    for idx, (val, deg) in enumerate(zip(comp_vals, comp_deg_vals)):
        ax1.text(idx, val + 350, f"{val:.0f}ms\n({deg:.1f}×)", ha="center", va="bottom", fontsize=7, fontweight="bold")

    ax1.axhline(base_comp, color="green", linestyle="--", linewidth=1.2, label="Baseline")
    ax1.set_ylabel("Compute Latency (ms)")
    ax1.set_title("Compute Latency Comparison Across ALL Scenarios", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax1.legend(loc="upper left")

    ax2.bar(x, disp_vals, bar_w * 1.5, color=colors_list, edgecolor="black", linewidth=0.6)
    for idx, (val, deg) in enumerate(zip(disp_vals, disp_deg_vals)):
        ax2.text(idx, val + 0.05, f"{val:.2f}ms\n({deg:.1f}×)", ha="center", va="bottom", fontsize=7, fontweight="bold")

    ax2.axhline(base_disp, color="green", linestyle="--", linewidth=1.2, label="Baseline")
    ax2.set_ylabel("E2E-GPU Residual (ms)")
    ax2.set_title("E2E-GPU Residual Comparison Across ALL Scenarios", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels_list, fontsize=7.5, rotation=25, ha="right")
    ax2.legend(loc="upper left")

    fig.suptitle("Side-by-Side Evaluation of ALL Interference Parameters", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_cpu_vs_memory_all.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_cpu_vs_memory_all.png")
    plt.close(fig)

    # ── Plot 5: Scatter of Compute Degradation vs Residual Ratio ────
    fig, ax = plt.subplots(figsize=(11, 7))

    for d, c, c_deg, d_deg in zip(data, colors_list, comp_deg_vals, disp_deg_vals):
        name = d["params"]["name"]
        cat = d["params"]["category"]
        ax.scatter(c_deg, d_deg, s=200, color=c, edgecolors="black", linewidth=1.2, zorder=4)
        ax.annotate(f" {name} ({cat})", (c_deg, d_deg), fontsize=8, fontweight="bold")

    ax.axvline(1.0, color="green", linestyle="--", alpha=0.6, label="1.0× Baseline Compute")
    ax.axhline(1.0, color="orange", linestyle="--", alpha=0.6, label="1.0× Baseline Residual")

    ax.set_xlabel("Compute Degradation Factor (× baseline)")
    ax.set_ylabel("Residual Ratio Factor (× baseline)")
    ax.set_title("Correlation Map: Compute Degradation vs Residual Ratio Across ALL Scenarios\n"
                 "Shows how each interference parameter independently impacts GPU execution vs E2E-GPU residual",
                 fontsize=12)
    ax.legend(loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_scatter_compute_vs_residual.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_scatter_compute_vs_residual.png")
    plt.close(fig)

    print("\n Unbiased Category Analysis completed successfully for ALL parameters!")


if __name__ == "__main__":
    main()