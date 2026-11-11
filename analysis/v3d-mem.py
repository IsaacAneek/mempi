#!/usr/bin/env python3
"""
v3d-mem.py  ─  V3D Performance Counters vs Latencies Across ALL Parameters
===========================================================================
Correlates V3D hardware performance counters with all interference parameters:
  - Baseline
  - CPU-side contentions (mutex, prime, threads)
  - Page-fault stressors (stress-ng fault/mmap)
  - Cache-resident & cache-evicting memory stressors
  - DRAM streaming & random access
  - Coherence & thread sweep

Key counters analyzed:
  - L2T cache hit/miss rates
  - TMU stall cycles
  - AXI bus read/write wait cycles
  - QPU stall breakdown (TMU, uniforms, wait-bubble)
  - Memory read/write transaction counts
  - Correlation with Compute Latency and E2E-GPU Residual (E2E - GPU timer)

Plots generated (saved to analysis/plots/):
  1. v3d_mem_l2t_cache.png:
     L2T cache hit rate (%) & absolute hit/miss counts across EVERY scenario.
  2. v3d_mem_stall_breakdown.png:
     V3D stall cycles breakdown (TMU, L2T, QPU) across EVERY scenario.
  3. v3d_mem_axi_bus.png:
     AXI memory bus read/write wait cycles & stalled transactions across EVERY scenario.
  4. v3d_mem_qpu_breakdown.png:
     QPU cycle breakdown: active vs stalls vs memory wait-bubbles across EVERY scenario.
  5. v3d_mem_traffic.png:
     Memory traffic (core vs AXI transactions) across EVERY scenario.
  6. v3d_mem_counter_heatmap.png:
     Normalized heatmap of all key counters across EVERY scenario.
  7. v3d_mem_hardware_vs_residual.png:
     Hardware AXI wait cycles & L2T stalls vs Compute and E2E-GPU Residuals across EVERY scenario.
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
    load_v3d_counters,
    get_active_v3d,
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


def aggregate_v3d_counters(folder):
    """
    Load V3D counters, keep only active windows, and sum values per counter
    across all active windows. Returns a dict: counter_name → total_value.
    """
    df = load_v3d_counters(folder)
    if df.empty:
        return {}

    window_sums = df.groupby("window")["value"].sum()
    active_wins = window_sums[window_sums > 0].index
    active = df[df["window"].isin(active_wins)]

    totals = active.groupby("counter_name")["value"].sum().to_dict()
    return totals


def main():
    data = load_all()
    if not data:
        print("No data found!")
        return

    # Sort deterministically: all scenarios included, with read/write counterpart pairs consecutive!
    data.sort(key=pair_sort_key)

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 4120.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    # Aggregate counters for each scenario
    agg = {}
    for d in data:
        name = d["params"]["name"]
        agg[name] = aggregate_v3d_counters(d["folder"])

    names = [d["params"]["name"] for d in data]

    # Split data into Part 1 (CPU & Cache <= 4 MiB) and Part 2 (DRAM, Sweeps, System >= 8 MiB)
    data_p1, data_p2 = split_data_parts(data)

    bar_w = 0.38
    x1, ticks1, labels1 = compute_pair_positions(data_p1, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)
    x2, ticks2, labels2 = compute_pair_positions(data_p2, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)

    names1 = [d["params"]["name"] for d in data_p1]
    names2 = [d["params"]["name"] for d in data_p2]

    colors1 = [scenario_color(d["params"]) for d in data_p1]
    colors2 = [scenario_color(d["params"]) for d in data_p2]

    # Legend elements for Read vs Write distinction
    legend_read = Patch(facecolor="#9E9E9E", edgecolor="black", label="Read (solid)")
    legend_write = Patch(facecolor="#9E9E9E", edgecolor="black", hatch="//", label="Write (hatched //)")

    def get_counter(name, counter):
        return agg.get(name, {}).get(counter, 0)

    # ── Plot 1: L2T Cache Hit Rate (Split: Part 1 vs Part 2) ──────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(20, 11))

    # Row 0: Part 1
    l2t_hits1 = [get_counter(n, "L2T-total-cache-hit") for n in names1]
    l2t_miss1 = [get_counter(n, "L2T-total-cache-miss") for n in names1]
    l2t_tot1 = [h + m if (h + m) > 0 else 1 for h, m in zip(l2t_hits1, l2t_miss1)]
    hit_rate1 = [h / t * 100 for h, t in zip(l2t_hits1, l2t_tot1)]

    bars1 = axes[0, 0].bar(x1, hit_rate1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d, val in zip(bars1, data_p1, hit_rate1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        axes[0, 0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{val:.1f}%", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    axes[0, 0].set_ylabel("L2T Hit Rate (%)")
    axes[0, 0].set_title("Part 1: L2T Cache Hit Rate (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 0].set_xticks(ticks1)
    axes[0, 0].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 0].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    axes[0, 0].set_ylim(0, 108)
    h1, _ = axes[0, 0].get_legend_handles_labels()
    h1.extend([legend_read, legend_write])
    axes[0, 0].legend(handles=h1, loc="lower left", fontsize=8)

    miss_m1 = [m / 1e6 for m in l2t_miss1]
    bars_m1 = axes[0, 1].bar(x1, miss_m1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d, val in zip(bars_m1, data_p1, miss_m1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if val > 0.05:
            axes[0, 1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                            f"{val:.1f}M", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    axes[0, 1].set_ylabel("L2T Misses (M)")
    axes[0, 1].set_title("Part 1: L2T Cache Misses (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 1].set_xticks(ticks1)
    axes[0, 1].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 1].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    h_m1, _ = axes[0, 1].get_legend_handles_labels()
    h_m1.extend([legend_read, legend_write])
    axes[0, 1].legend(handles=h_m1, loc="upper left", fontsize=8)

    # Row 1: Part 2
    l2t_hits2 = [get_counter(n, "L2T-total-cache-hit") for n in names2]
    l2t_miss2 = [get_counter(n, "L2T-total-cache-miss") for n in names2]
    l2t_tot2 = [h + m if (h + m) > 0 else 1 for h, m in zip(l2t_hits2, l2t_miss2)]
    hit_rate2 = [h / t * 100 for h, t in zip(l2t_hits2, l2t_tot2)]

    bars2 = axes[1, 0].bar(x2, hit_rate2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d, val in zip(bars2, data_p2, hit_rate2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        axes[1, 0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                        f"{val:.1f}%", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    axes[1, 0].set_ylabel("L2T Hit Rate (%)")
    axes[1, 0].set_title("Part 2: L2T Cache Hit Rate (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 0].set_xticks(ticks2)
    axes[1, 0].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 0].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    axes[1, 0].set_ylim(0, 108)
    h2, _ = axes[1, 0].get_legend_handles_labels()
    h2.extend([legend_read, legend_write])
    axes[1, 0].legend(handles=h2, loc="lower left", fontsize=8)

    miss_m2 = [m / 1e6 for m in l2t_miss2]
    bars_m2 = axes[1, 1].bar(x2, miss_m2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d, val in zip(bars_m2, data_p2, miss_m2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if val > 0.05:
            axes[1, 1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                            f"{val:.1f}M", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    axes[1, 1].set_ylabel("L2T Misses (M)")
    axes[1, 1].set_title("Part 2: L2T Cache Misses (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 1].set_xticks(ticks2)
    axes[1, 1].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 1].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    h_m2, _ = axes[1, 1].get_legend_handles_labels()
    h_m2.extend([legend_read, legend_write])
    axes[1, 1].legend(handles=h_m2, loc="upper left", fontsize=8)

    fig.suptitle("V3D L2T Cache Behavior Across ALL Interference Parameters (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_l2t_cache.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_l2t_cache.png")
    plt.close(fig)

    # ── Plot 2: Stall Cycles Breakdown (Split: Part 1 vs Part 2) ──────────────────────
    stall_counters = [
        ("TMU-stalled-cycles", "TMU Stalled"),
        ("L2T-stalls-mem", "L2T Mem Stalls"),
        ("L2T-stalls-no-wid", "L2T No-WID Stalls"),
        ("L2T-stalls-read-data", "L2T Read-Data Stalls"),
        ("QPU-stalls-TMU", "QPU→TMU Stalls"),
        ("QPU-stalls-uniforms", "QPU→Uniform Stalls"),
    ]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))
    n_counters = len(stall_counters)
    b_w = bar_w / n_counters
    stall_colors = plt.cm.Set2(np.linspace(0, 1, n_counters))

    # Panel 1: Part 1
    for j, (ctr, label) in enumerate(stall_counters):
        vals1 = [get_counter(n, ctr) / 1e6 for n in names1]
        offset = (j - n_counters / 2 + 0.5) * b_w
        ax1.bar(x1 + offset, vals1, b_w, label=label, color=stall_colors[j],
                edgecolor="black", linewidth=0.3)

    ax1.set_ylabel("Stall Cycles (millions)")
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — V3D Pipeline Stall Cycles", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.legend(fontsize=8, loc="upper left")

    # Panel 2: Part 2
    for j, (ctr, label) in enumerate(stall_counters):
        vals2 = [get_counter(n, ctr) / 1e6 for n in names2]
        offset = (j - n_counters / 2 + 0.5) * b_w
        ax2.bar(x2 + offset, vals2, b_w, label=label, color=stall_colors[j],
                edgecolor="black", linewidth=0.3)

    ax2.set_xlabel("Interference Scenario (Read/Write Bar Pairs)")
    ax2.set_ylabel("Stall Cycles (millions)")
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & VM (8 MiB to 256 MiB+) — V3D Pipeline Stall Cycles", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.legend(fontsize=8, loc="upper left")

    fig.suptitle("V3D Pipeline Stall Cycles Breakdown Across ALL Parameters (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_stall_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_stall_breakdown.png")
    plt.close(fig)

    # ── Plot 3: AXI Bus Wait Cycles (Split: Part 1 vs Part 2) ─────────────────────────
    fig, axes = plt.subplots(2, 2, figsize=(20, 11))

    # Row 0: Part 1
    axi_r1 = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names1]
    axi_w1 = [get_counter(n, "AXI-write-wait-cycles") / 1e9 for n in names1]

    b_ar1 = axes[0, 0].bar(x1, axi_r1, bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d, r in zip(b_ar1, data_p1, axi_r1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if r > 0.05:
            axes[0, 0].text(bar.get_x() + bar.get_width() / 2, r + 0.05, f"{r:.1f}B", ha="center", va="bottom", fontsize=6.5, rotation=90)
    axes[0, 0].set_ylabel("Wait Cycles (billions)")
    axes[0, 0].set_title("Part 1: AXI Read Wait Cycles (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 0].set_xticks(ticks1)
    axes[0, 0].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 0].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    h_ar1, _ = axes[0, 0].get_legend_handles_labels()
    h_ar1.extend([legend_read, legend_write])
    axes[0, 0].legend(handles=h_ar1, loc="upper left", fontsize=8)

    b_aw1 = axes[0, 1].bar(x1, axi_w1, bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d, w in zip(b_aw1, data_p1, axi_w1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if w > 0.05:
            axes[0, 1].text(bar.get_x() + bar.get_width() / 2, w + 0.05, f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, rotation=90)
    axes[0, 1].set_ylabel("Wait Cycles (billions)")
    axes[0, 1].set_title("Part 1: AXI Write Wait Cycles (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 1].set_xticks(ticks1)
    axes[0, 1].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 1].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    h_aw1, _ = axes[0, 1].get_legend_handles_labels()
    h_aw1.extend([legend_read, legend_write])
    axes[0, 1].legend(handles=h_aw1, loc="upper left", fontsize=8)

    # Row 1: Part 2
    axi_r2 = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names2]
    axi_w2 = [get_counter(n, "AXI-write-wait-cycles") / 1e9 for n in names2]

    b_ar2 = axes[1, 0].bar(x2, axi_r2, bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d, r in zip(b_ar2, data_p2, axi_r2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if r > 0.05:
            axes[1, 0].text(bar.get_x() + bar.get_width() / 2, r + 0.05, f"{r:.1f}B", ha="center", va="bottom", fontsize=6.5, rotation=90)
    axes[1, 0].set_ylabel("Wait Cycles (billions)")
    axes[1, 0].set_title("Part 2: AXI Read Wait Cycles (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 0].set_xticks(ticks2)
    axes[1, 0].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 0].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    h_ar2, _ = axes[1, 0].get_legend_handles_labels()
    h_ar2.extend([legend_read, legend_write])
    axes[1, 0].legend(handles=h_ar2, loc="upper left", fontsize=8)

    b_aw2 = axes[1, 1].bar(x2, axi_w2, bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d, w in zip(b_aw2, data_p2, axi_w2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        if w > 0.05:
            axes[1, 1].text(bar.get_x() + bar.get_width() / 2, w + 0.05, f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, rotation=90)
    axes[1, 1].set_ylabel("Wait Cycles (billions)")
    axes[1, 1].set_title("Part 2: AXI Write Wait Cycles (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 1].set_xticks(ticks2)
    axes[1, 1].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 1].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    h_aw2, _ = axes[1, 1].get_legend_handles_labels()
    h_aw2.extend([legend_read, legend_write])
    axes[1, 1].legend(handles=h_aw2, loc="upper left", fontsize=8)

    fig.suptitle("AXI Memory Bus Contention: Hardware Wait Cycles Across ALL Parameters (Split: Part 1 vs Part 2)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_axi_bus.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_axi_bus.png")
    plt.close(fig)

    # ── Plot 4: QPU Cycle Breakdown (Split: Part 1 vs Part 2) ─────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 1: Part 1
    qpu_act1 = [get_counter(n, "QPU-active") / 1e6 for n in names1]
    qpu_stl1 = [get_counter(n, "QPU-stalls") / 1e6 for n in names1]
    qpu_bub1 = [get_counter(n, "QPU-wait-bubble") / 1e6 for n in names1]
    qpu_ic1 = [get_counter(n, "QPU-ic-miss-bubble") / 1e6 for n in names1]

    ax1.bar(x1, qpu_act1, bar_w, label="QPU Active", color="#4CAF50", edgecolor="black", linewidth=0.3)
    ax1.bar(x1, qpu_stl1, bar_w, bottom=qpu_act1, label="QPU Stalls", color="#FF9800", edgecolor="black", linewidth=0.3)
    bot2_1 = [a + s for a, s in zip(qpu_act1, qpu_stl1)]
    ax1.bar(x1, qpu_bub1, bar_w, bottom=bot2_1, label="QPU Wait Bubble", color="#F44336", edgecolor="black", linewidth=0.3)
    bot3_1 = [b + w for b, w in zip(bot2_1, qpu_bub1)]
    ax1.bar(x1, qpu_ic1, bar_w, bottom=bot3_1, label="QPU IC-Miss Bubble", color="#9C27B0", edgecolor="black", linewidth=0.3)

    for i in range(len(names1)):
        total = qpu_act1[i] + qpu_stl1[i] + qpu_bub1[i] + qpu_ic1[i]
        if total > 0:
            pct = qpu_bub1[i] / total * 100
            ax1.text(x1[i], total + 30, f"{pct:.0f}%", ha="center", fontsize=6.5, fontweight="bold", rotation=90)

    ax1.set_ylabel("Cycles (millions)")
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — QPU Execution Breakdown", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.legend(loc="upper left", fontsize=8)

    # Panel 2: Part 2
    qpu_act2 = [get_counter(n, "QPU-active") / 1e6 for n in names2]
    qpu_stl2 = [get_counter(n, "QPU-stalls") / 1e6 for n in names2]
    qpu_bub2 = [get_counter(n, "QPU-wait-bubble") / 1e6 for n in names2]
    qpu_ic2 = [get_counter(n, "QPU-ic-miss-bubble") / 1e6 for n in names2]

    ax2.bar(x2, qpu_act2, bar_w, label="QPU Active", color="#4CAF50", edgecolor="black", linewidth=0.3)
    ax2.bar(x2, qpu_stl2, bar_w, bottom=qpu_act2, label="QPU Stalls", color="#FF9800", edgecolor="black", linewidth=0.3)
    bot2_2 = [a + s for a, s in zip(qpu_act2, qpu_stl2)]
    ax2.bar(x2, qpu_bub2, bar_w, bottom=bot2_2, label="QPU Wait Bubble", color="#F44336", edgecolor="black", linewidth=0.3)
    bot3_2 = [b + w for b, w in zip(bot2_2, qpu_bub2)]
    ax2.bar(x2, qpu_ic2, bar_w, bottom=bot3_2, label="QPU IC-Miss Bubble", color="#9C27B0", edgecolor="black", linewidth=0.3)

    for i in range(len(names2)):
        total = qpu_act2[i] + qpu_stl2[i] + qpu_bub2[i] + qpu_ic2[i]
        if total > 0:
            pct = qpu_bub2[i] / total * 100
            ax2.text(x2[i], total + 30, f"{pct:.0f}%", ha="center", fontsize=6.5, fontweight="bold", rotation=90)

    ax2.set_xlabel("Interference Scenario (Read/Write Bar Pairs)")
    ax2.set_ylabel("Cycles (millions)")
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & VM (8 MiB to 256 MiB+) — QPU Execution Breakdown", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.legend(loc="upper left", fontsize=8)

    fig.suptitle("QPU Execution Breakdown: Active vs Stalls vs Wait Bubbles (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_qpu_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_qpu_breakdown.png")
    plt.close(fig)

    # ── Plot 5: Memory Traffic (Split: Part 1 vs Part 2) ──────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))
    b_sub = bar_w / 4.0

    # Panel 1: Part 1
    mem_r1 = [get_counter(n, "core-memory-reads") / 1e6 for n in names1]
    mem_w1 = [get_counter(n, "core-memory-writes") / 1e6 for n in names1]
    axi_rt1 = [get_counter(n, "AXI-read-trans") / 1e6 for n in names1]
    axi_wt1 = [get_counter(n, "AXI-write-trans") / 1e6 for n in names1]

    ax1.bar(x1 - 1.5 * b_sub, mem_r1, b_sub, label="Core Mem Reads", color="#1565C0", edgecolor="black", linewidth=0.3)
    ax1.bar(x1 - 0.5 * b_sub, mem_w1, b_sub, label="Core Mem Writes", color="#42A5F5", edgecolor="black", linewidth=0.3)
    ax1.bar(x1 + 0.5 * b_sub, axi_rt1, b_sub, label="AXI Read Trans", color="#C62828", edgecolor="black", linewidth=0.3)
    ax1.bar(x1 + 1.5 * b_sub, axi_wt1, b_sub, label="AXI Write Trans", color="#EF5350", edgecolor="black", linewidth=0.3)

    ax1.set_ylabel("Transactions (millions)")
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Core & AXI Transactions", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.legend(fontsize=8.5, loc="upper left")

    # Panel 2: Part 2
    mem_r2 = [get_counter(n, "core-memory-reads") / 1e6 for n in names2]
    mem_w2 = [get_counter(n, "core-memory-writes") / 1e6 for n in names2]
    axi_rt2 = [get_counter(n, "AXI-read-trans") / 1e6 for n in names2]
    axi_wt2 = [get_counter(n, "AXI-write-trans") / 1e6 for n in names2]

    ax2.bar(x2 - 1.5 * b_sub, mem_r2, b_sub, label="Core Mem Reads", color="#1565C0", edgecolor="black", linewidth=0.3)
    ax2.bar(x2 - 0.5 * b_sub, mem_w2, b_sub, label="Core Mem Writes", color="#42A5F5", edgecolor="black", linewidth=0.3)
    ax2.bar(x2 + 0.5 * b_sub, axi_rt2, b_sub, label="AXI Read Trans", color="#C62828", edgecolor="black", linewidth=0.3)
    ax2.bar(x2 + 1.5 * b_sub, axi_wt2, b_sub, label="AXI Write Trans", color="#EF5350", edgecolor="black", linewidth=0.3)

    ax2.set_xlabel("Interference Scenario (Read/Write Bar Pairs)")
    ax2.set_ylabel("Transactions (millions)")
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & VM (8 MiB to 256 MiB+) — Core & AXI Transactions", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.legend(fontsize=8.5, loc="upper left")

    fig.suptitle("V3D Memory Traffic: Core & AXI Transactions Across ALL Parameters (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_traffic.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_traffic.png")
    plt.close(fig)

    # ── Plot 6: Normalized Heatmap of Key Counters (Split: Part 1 vs Part 2) ───────────
    key_counters = [
        "cycle-count", "core-active", "compute-active-cycles",
        "L2T-total-cache-hit", "L2T-total-cache-miss",
        "L2T-stalls-mem", "L2T-stalls-read-data",
        "TMU-active-cycles", "TMU-stalled-cycles",
        "QPU-active", "QPU-stalls", "QPU-stalls-TMU",
        "QPU-wait-bubble",
        "AXI-read-wait-cycles", "AXI-write-wait-cycles",
        "AXI-read-trans", "AXI-write-trans",
        "core-memory-reads", "core-memory-writes",
    ]

    base_counters = {}
    for ctr in key_counters:
        base_val = get_counter(names1[0], ctr)
        base_counters[ctr] = base_val if base_val > 0 else 1

    mat1 = []
    for ctr in key_counters:
        bv = base_counters[ctr]
        mat1.append([get_counter(n, ctr) / bv for n in names1])
    mat1 = np.array(mat1, dtype=float)

    mat2 = []
    for ctr in key_counters:
        bv = base_counters[ctr]
        mat2.append([get_counter(n, ctr) / bv for n in names2])
    mat2 = np.array(mat2, dtype=float)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 14))

    im1 = ax1.imshow(mat1, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=6)
    ax1.set_xticks(range(len(names1)))
    ax1.set_xticklabels([nice_label(n, d["params"]).replace("\n", " ") for n, d in zip(names1, data_p1)],
                        fontsize=7.5, rotation=45, ha="right")
    ax1.set_yticks(range(len(key_counters)))
    ax1.set_yticklabels(key_counters, fontsize=8.5)
    for i in range(len(key_counters)):
        for j in range(len(names1)):
            val = mat1[i, j]
            tc = "white" if val > 4 else "black"
            ax1.text(j, i, f"{val:.1f}×", ha="center", va="center", fontsize=6, color=tc, fontweight="bold")
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — Normalized Counters", fontsize=11, fontweight="bold")

    im2 = ax2.imshow(mat2, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=6)
    ax2.set_xticks(range(len(names2)))
    ax2.set_xticklabels([nice_label(n, d["params"]).replace("\n", " ") for n, d in zip(names2, data_p2)],
                        fontsize=7.5, rotation=45, ha="right")
    ax2.set_yticks(range(len(key_counters)))
    ax2.set_yticklabels(key_counters, fontsize=8.5)
    for i in range(len(key_counters)):
        for j in range(len(names2)):
            val = mat2[i, j]
            tc = "white" if val > 4 else "black"
            ax2.text(j, i, f"{val:.1f}×", ha="center", va="center", fontsize=6, color=tc, fontweight="bold")
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & VM (8 MiB to 256 MiB+) — Normalized Counters", fontsize=11, fontweight="bold")

    fig.subplots_adjust(right=0.91, hspace=0.35)
    cbar_ax = fig.add_axes([0.93, 0.15, 0.015, 0.7])
    cbar = fig.colorbar(im2, cax=cbar_ax)
    cbar.set_label("× Baseline", fontsize=10)

    fig.suptitle("V3D Hardware Counters Normalized to Baseline Across EVERY Parameter (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_counter_heatmap.png"), dpi=150, bbox_inches="tight")
    print(f"  → {PLOT_DIR}/v3d_mem_counter_heatmap.png")
    plt.close(fig)

    # ── Plot 7: Hardware Contention vs Compute & E2E-GPU Residual (Split: Part 1 vs Part 2) ─
    fig, axes = plt.subplots(2, 2, figsize=(20, 11))

    # Row 0: Part 1
    axi_w_b1 = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names1]
    comp_lats1 = [d["gpu"]["compute_ms"] for d in data_p1]
    disp_lats1 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p1]

    # Row 0, Col 0: Part 1 AXI Read Wait vs Compute Latency
    ax1_twin = axes[0, 0].twinx()
    b_a1 = axes[0, 0].bar(x1, axi_w_b1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6)
    for bar, d in zip(b_a1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c1 = ax1_twin.plot(x1, comp_lats1, "ro-", markersize=5, linewidth=1.4)
    for bar, w in zip(b_a1, axi_w_b1):
        if w > 0.05:
            axes[0, 0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                            f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    for i_x, c_lat in zip(x1, comp_lats1):
        ax1_twin.text(i_x, c_lat + 200, f"{c_lat:.0f}", ha="center", va="bottom",
                      fontsize=6.5, fontweight="bold", color="red", rotation=90)
    axes[0, 0].set_ylabel("AXI Read Wait (B)")
    ax1_twin.set_ylabel("Compute Latency (ms)", color="red")
    axes[0, 0].set_title("Part 1: AXI Read Wait vs Compute Latency (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 0].set_xticks(ticks1)
    axes[0, 0].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 0].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    axes[0, 0].legend([b_a1, l_c1[0], legend_read, legend_write], ["AXI Read Wait", "Compute Latency", "Read", "Write"], loc="upper left", fontsize=7.5)

    # Row 0, Col 1: Part 1 AXI Read Wait vs Residual
    ax2_twin = axes[0, 1].twinx()
    b_a2 = axes[0, 1].bar(x1, axi_w_b1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6)
    for bar, d in zip(b_a2, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_d1 = ax2_twin.plot(x1, disp_lats1, "s--", color="#D84315", markersize=5, linewidth=1.4)
    for bar, w in zip(b_a2, axi_w_b1):
        if w > 0.05:
            axes[0, 1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                            f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    for i_x, d_lat in zip(x1, disp_lats1):
        ax2_twin.text(i_x, d_lat + 0.08, f"{d_lat:.2f}", ha="center", va="bottom",
                      fontsize=6.5, fontweight="bold", color="#D84315", rotation=90)
    axes[0, 1].set_ylabel("AXI Read Wait (B)")
    ax2_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315")
    axes[0, 1].set_title("Part 1: AXI Read Wait vs E2E-GPU Residual (Baseline to 4 MiB)", fontsize=10, fontweight="bold")
    axes[0, 1].set_xticks(ticks1)
    axes[0, 1].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[0, 1].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    axes[0, 1].legend([b_a2, l_d1[0], legend_read, legend_write], ["AXI Read Wait", "Residual", "Read", "Write"], loc="upper left", fontsize=7.5)

    # Row 1: Part 2
    axi_w_b2 = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names2]
    comp_lats2 = [d["gpu"]["compute_ms"] for d in data_p2]
    disp_lats2 = [d["gpu"]["e2e_minus_gpu_ms"] for d in data_p2]

    # Row 1, Col 0: Part 2 AXI Read Wait vs Compute Latency
    ax3_twin = axes[1, 0].twinx()
    b_a3 = axes[1, 0].bar(x2, axi_w_b2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6)
    for bar, d in zip(b_a3, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c2 = ax3_twin.plot(x2, comp_lats2, "ro-", markersize=5, linewidth=1.4)
    for bar, w in zip(b_a3, axi_w_b2):
        if w > 0.05:
            axes[1, 0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                            f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    for i_x, c_lat in zip(x2, comp_lats2):
        ax3_twin.text(i_x, c_lat + 200, f"{c_lat:.0f}", ha="center", va="bottom",
                      fontsize=6.5, fontweight="bold", color="red", rotation=90)
    axes[1, 0].set_xlabel("Interference Scenario (Read/Write Bar Pairs)")
    axes[1, 0].set_ylabel("AXI Read Wait (B)")
    ax3_twin.set_ylabel("Compute Latency (ms)", color="red")
    axes[1, 0].set_title("Part 2: AXI Read Wait vs Compute Latency (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 0].set_xticks(ticks2)
    axes[1, 0].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 0].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    axes[1, 0].legend([b_a3, l_c2[0], legend_read, legend_write], ["AXI Read Wait", "Compute Latency", "Read", "Write"], loc="upper left", fontsize=7.5)

    # Row 1, Col 1: Part 2 AXI Read Wait vs Residual
    ax4_twin = axes[1, 1].twinx()
    b_a4 = axes[1, 1].bar(x2, axi_w_b2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6)
    for bar, d in zip(b_a4, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_d2 = ax4_twin.plot(x2, disp_lats2, "s--", color="#D84315", markersize=5, linewidth=1.4)
    for bar, w in zip(b_a4, axi_w_b2):
        if w > 0.05:
            axes[1, 1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                            f"{w:.1f}B", ha="center", va="bottom", fontsize=6.5, fontweight="bold", rotation=90)
    for i_x, d_lat in zip(x2, disp_lats2):
        ax4_twin.text(i_x, d_lat + 0.08, f"{d_lat:.2f}", ha="center", va="bottom",
                      fontsize=6.5, fontweight="bold", color="#D84315", rotation=90)
    axes[1, 1].set_xlabel("Interference Scenario (Read/Write Bar Pairs)")
    axes[1, 1].set_ylabel("AXI Read Wait (B)")
    ax4_twin.set_ylabel("E2E-GPU Residual (ms)", color="#D84315")
    axes[1, 1].set_title("Part 2: AXI Read Wait vs E2E-GPU Residual (8 MiB to 256 MiB+)", fontsize=10, fontweight="bold")
    axes[1, 1].set_xticks(ticks2)
    axes[1, 1].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[1, 1].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    axes[1, 1].legend([b_a4, l_d2[0], legend_read, legend_write], ["AXI Read Wait", "Residual", "Read", "Write"], loc="upper left", fontsize=7.5)

    fig.suptitle("Interconnect Contention: Impact on GPU Kernel vs E2E-GPU Residual (Split: Part 1 vs Part 2)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_hardware_vs_residual.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_hardware_vs_residual.png")
    plt.close(fig)

    # ── Print Summary Table (EVERY Scenario) ──────────────────────────────
    print("\n" + "=" * 125)
    print("V3D COUNTERS vs LATENCIES ACROSS ALL PARAMETERS – SUMMARY")
    print("=" * 125)

    highlight = [
        ("L2T-total-cache-hit", "L2T Cache Hits"),
        ("L2T-total-cache-miss", "L2T Cache Misses"),
        ("TMU-stalled-cycles", "TMU Stalled Cycles"),
        ("L2T-stalls-mem", "L2T Memory Stalls"),
        ("QPU-active", "QPU Active Cycles"),
        ("QPU-stalls", "QPU Total Stalls"),
        ("QPU-wait-bubble", "QPU Wait Bubble"),
        ("AXI-read-wait-cycles", "AXI Read Wait"),
        ("AXI-write-wait-cycles", "AXI Write Wait"),
    ]

    header = f"{'Metric / Counter':<22s}"
    for n in names:
        header += f"  {n:>9s}"
    print(header)
    print("-" * (22 + 11 * len(names)))

    r_comp = f"{'Compute Lat (ms)':<22s}"
    r_disp = f"{'E2E-GPU Resid (ms)':<22s}"
    for d in data:
        r_comp += f"  {d['gpu']['compute_ms']:>9.0f}"
        r_disp += f"  {d['gpu']['e2e_minus_gpu_ms']:>9.3f}"
    print(r_comp)
    print(r_disp)
    print("-" * (22 + 11 * len(names)))

    for ctr, label in highlight:
        row = f"{label:<22s}"
        vals = [get_counter(n, ctr) for n in names]
        for v in vals:
            if v > 1e9:
                row += f"  {v / 1e9:>8.1f}B"
            elif v > 1e6:
                row += f"  {v / 1e6:>8.1f}M"
            elif v > 1e3:
                row += f"  {v / 1e3:>8.1f}K"
            else:
                row += f"  {v:>9d}"
        print(row)


if __name__ == "__main__":
    main()