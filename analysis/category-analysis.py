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
  5. category_comparison_compute_vs_residual.png:
     Paired bar comparison of Compute Degradation vs Residual Ratio for EVERY scenario.
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
    return pair_sort_key(d)


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    # Sort deterministically: all scenarios included, with read/write counterpart pairs consecutive!
    data.sort(key=pair_sort_key)

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    names = [d["params"]["name"] for d in data]
    colors_list = [scenario_color(d["params"]) for d in data]

    # Split data into Part 1 (CPU & Cache <= 4 MiB) and Part 2 (DRAM, Sweeps, System >= 8 MiB)
    data_p1, data_p2 = split_data_parts(data)

    bar_w = 0.38
    x1, ticks1, labels1 = compute_pair_positions(data_p1, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)
    x2, ticks2, labels2 = compute_pair_positions(data_p2, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)

    colors1 = [scenario_color(d["params"]) for d in data_p1]
    colors2 = [scenario_color(d["params"]) for d in data_p2]

    comp_vals1 = [d["gpu"]["compute_ms"] for d in data_p1]
    disp_vals1 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p1]
    comp_deg1 = [c / base_comp for c in comp_vals1]
    disp_deg1 = [disp / base_disp for disp in disp_vals1]

    comp_vals2 = [d["gpu"]["compute_ms"] for d in data_p2]
    disp_vals2 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p2]
    comp_deg2 = [c / base_comp for c in comp_vals2]
    disp_deg2 = [disp / base_disp for disp in disp_vals2]

    comp_vals = [d["gpu"]["compute_ms"] for d in data]
    disp_vals = [d["gpu"]["e2e_minus_gpu_ms"] for d in data]
    comp_deg_vals = [c / base_comp for c in comp_vals]
    disp_deg_vals = [disp / base_disp for disp in disp_vals]

    # Legend elements for Read vs Write distinction
    legend_read = Patch(facecolor="#9E9E9E", edgecolor="black", label="Read (solid)")
    legend_write = Patch(facecolor="#9E9E9E", edgecolor="black", hatch="//", label="Write (hatched //)")

    # Group scenarios by category
    by_cat = {}
    for d in data:
        cat = d["params"]["category"]
        by_cat.setdefault(cat, []).append(d)

    print("\n" + "=" * 95)
    print("ALL SCENARIOS INCLUDED IN ANALYSIS (NO OMISSIONS) – PAIRED ORDER:")
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

    # ── Plot 2: Compute Latency Across EVERY Scenario (Split: Part 1 & Part 2) ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1 (CPU & Cache Hierarchy <= 4 MiB)
    ax1_twin = ax1.twinx()
    b1 = ax1.bar(x1, comp_vals1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b1, data_p1, comp_vals1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 150,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)

    ax1.axhline(base_comp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_comp:.0f} ms")
    ax1.set_ylabel("Compute Latency (ms)", fontsize=10)
    ax1.set_title("Part 1: CPU-Side Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    y1_max = max(comp_vals1) * 1.15
    ax1.set_ylim(0, y1_max)
    ax1_twin.set_ylim(0, y1_max / base_comp)
    ax1_twin.set_ylabel("Degradation Factor (× baseline)", fontsize=10)
    handles1, _ = ax1.get_legend_handles_labels()
    handles1.extend([legend_read, legend_write])
    ax1.legend(handles=handles1, loc="upper left", fontsize=8)

    # Panel 2: Part 2 (DRAM, Sweeps, Coherence, Page Faults >= 8 MiB)
    ax2_twin = ax2.twinx()
    b2 = ax2.bar(x2, comp_vals2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b2, data_p2, comp_vals2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 250,
                 f"{val:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)

    ax2.axhline(base_comp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_comp:.0f} ms")
    ax2.set_ylabel("Compute Latency (ms)", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    y2_max = max(comp_vals2) * 1.15
    ax2.set_ylim(0, y2_max)
    ax2_twin.set_ylim(0, y2_max / base_comp)
    ax2_twin.set_ylabel("Degradation Factor (× baseline)", fontsize=10)
    handles2, _ = ax2.get_legend_handles_labels()
    handles2.extend([legend_read, legend_write])
    ax2.legend(handles=handles2, loc="upper left", fontsize=8)

    fig.suptitle("GPU Compute Latency & Degradation Factor (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_all_scenarios_compute.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_all_scenarios_compute.png")
    plt.close(fig)

    # ── Plot 3: E2E-GPU Residual Across EVERY Scenario (Split: Part 1 & Part 2) ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    ax1_twin = ax1.twinx()
    b_d1 = ax1.bar(x1, disp_vals1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b_d1, data_p1, disp_vals1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                 f"{val:.3f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)

    ax1.axhline(base_disp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_disp:.3f} ms")
    ax1.set_ylabel("E2E-GPU Residual (ms)", fontsize=10)
    ax1.set_title("Part 1: CPU-Side Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    yd1_max = max(disp_vals1) * 1.2
    ax1.set_ylim(0, yd1_max)
    ax1_twin.set_ylim(0, yd1_max / base_disp)
    ax1_twin.set_ylabel("Residual Ratio (× baseline)", fontsize=10)
    h3_1, _ = ax1.get_legend_handles_labels()
    h3_1.extend([legend_read, legend_write])
    ax1.legend(handles=h3_1, loc="upper left", fontsize=8)

    # Panel 2: Part 2
    ax2_twin = ax2.twinx()
    b_d2 = ax2.bar(x2, disp_vals2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6)
    for bar, d, val in zip(b_d2, data_p2, disp_vals2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                 f"{val:.3f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)

    ax2.axhline(base_disp, color="green", linestyle="--", linewidth=1.2, label=f"Baseline: {base_disp:.3f} ms")
    ax2.set_ylabel("E2E-GPU Residual (ms)", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — Paired Read/Write", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    yd2_max = max(disp_vals2) * 1.2
    ax2.set_ylim(0, yd2_max)
    ax2_twin.set_ylim(0, yd2_max / base_disp)
    ax2_twin.set_ylabel("Residual Ratio (× baseline)", fontsize=10)
    h3_2, _ = ax2.get_legend_handles_labels()
    h3_2.extend([legend_read, legend_write])
    ax2.legend(handles=h3_2, loc="upper left", fontsize=8)

    fig.suptitle("E2E-GPU Residual (E2E - GPU timer) & Degradation Ratio (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_all_scenarios_residual.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_all_scenarios_residual.png")
    plt.close(fig)

    # ── Plot 4: Compute vs Residual Direct Comparison (Split: Part 1 & Part 2) ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    ax1_twin = ax1.twinx()
    b_c1 = ax1.bar(x1, comp_vals1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d in zip(b_c1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_d1 = ax1_twin.plot(x1, disp_vals1, "s--", color="#D84315", markersize=6, linewidth=1.5, label="E2E-GPU Residual (ms)")

    ax1.set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax1_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315", fontsize=10)
    ax1.set_title("Part 1: CPU & Cache Hierarchy Scenarios (Baseline to 4 MiB) — Compute vs Residual", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    lines_p4_1 = [b_c1, l_d1[0], legend_read, legend_write]
    labels_p4_1 = ["Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"]
    ax1.legend(lines_p4_1, labels_p4_1, loc="upper left", fontsize=8)

    # Panel 2: Part 2
    ax2_twin = ax2.twinx()
    b_c2 = ax2.bar(x2, comp_vals2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6, label="Compute Latency (ms)")
    for bar, d in zip(b_c2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_d2 = ax2_twin.plot(x2, disp_vals2, "s--", color="#D84315", markersize=6, linewidth=1.5, label="E2E-GPU Residual (ms)")

    ax2.set_ylabel("Compute Latency (ms)", color="black", fontsize=10)
    ax2_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315", fontsize=10)
    ax2.set_title("Part 2: DRAM, Sweeps, Coherence & Virtual Memory (8 MiB to 256 MiB+) — Compute vs Residual", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    lines_p4_2 = [b_c2, l_d2[0], legend_read, legend_write]
    labels_p4_2 = ["Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"]
    ax2.legend(lines_p4_2, labels_p4_2, loc="upper left", fontsize=8)

    fig.suptitle("Direct Comparison: Compute Latency vs E2E-GPU Residual (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_cpu_vs_memory_all.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_cpu_vs_memory_all.png")
    plt.close(fig)

    # ── Plot 5: Paired Horizontal Bar Comparison (Compute vs Residual Degradation) ──
    fig, ax = plt.subplots(figsize=(15, 22))

    bar_h = 0.35
    y_pos = np.arange(len(data))

    b1 = ax.barh(y_pos - bar_h / 2, comp_deg_vals, bar_h, label="Compute Degradation (× baseline)",
                 color="#EF5350", edgecolor="black", linewidth=0.5)
    b2 = ax.barh(y_pos + bar_h / 2, disp_deg_vals, bar_h, label="E2E-GPU Residual Degradation (× baseline)",
                 color="#FFA726", edgecolor="black", linewidth=0.5)

    for bar, val in zip(b1, comp_deg_vals):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}×", ha="left", va="center", fontsize=7, fontweight="bold", color="#B71C1C")

    for bar, val in zip(b2, disp_deg_vals):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}×", ha="left", va="center", fontsize=7, fontweight="bold", color="#E65100")

    ax.axvline(1.0, color="green", linestyle="--", linewidth=1.5, alpha=0.8, label="1.0× Baseline")
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{d['params']['name']} ({d['params']['category']})" for d in data], fontsize=7.5)
    ax.set_xlabel("Degradation Factor (× Baseline)")
    ax.set_title("Direct Comparison: Compute Degradation vs Residual Degradation Across ALL Parameters (Paired Order)",
                 fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "category_comparison_compute_vs_residual.png"), dpi=150)
    print(f"  → {PLOT_DIR}/category_comparison_compute_vs_residual.png")
    plt.close(fig)

    print("\n Unbiased Category Analysis completed successfully for ALL parameters!")


if __name__ == "__main__":
    main()