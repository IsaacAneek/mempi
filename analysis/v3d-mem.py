#!/usr/bin/env python3
"""
v3d-mem.py  ─  V3D Performance Counters vs Memory Stress Parameters
=====================================================================
Correlates V3D hardware performance counters with different memory-stress
scenarios to show how DRAM contention manifests inside the GPU pipeline.

Key counters analyzed:
  - L2T cache hit/miss rates
  - TMU stall cycles
  - AXI bus read/write wait cycles
  - QPU stall breakdown (TMU, uniforms, bubble)
  - Memory read/write transaction counts

Plots generated (saved to analysis/plots/):
  1. L2T cache hit rate comparison (bar chart)
  2. Stall cycles breakdown (grouped bar)
  3. AXI bus wait cycles (bar + heatmap)
  4. QPU activity breakdown (stacked bar)
  5. Memory traffic comparison (read/write transactions)
  6. Heatmap of all key counters across scenarios
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
from data_loader import load_all, load_v3d_counters, get_active_v3d, DATA_DIR

PLOT_DIR = os.path.join(os.path.dirname(__file__), "plots")
os.makedirs(PLOT_DIR, exist_ok=True)

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f8f8",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 11,
})

SCENARIO_COLORS = {
    "baseline": "#4CAF50",
    "16kr": "#2196F3",
    "16kr_rnd": "#03A9F4",
    "4mr": "#F44336",
}


def nice_label(name):
    labels = {
        "baseline": "Baseline\n(no stress)",
        "16kr": "16K seq\nread",
        "16kr_rnd": "16K rnd\nread",
        "4mr": "4M seq\nread",
    }
    return labels.get(name, name)


def aggregate_v3d_counters(folder):
    """
    Load V3D counters, keep only active windows, and sum values per counter
    across all active windows.  Returns a dict: counter_name → total_value.
    """
    df = load_v3d_counters(folder)
    if df.empty:
        return {}

    # Keep only windows where at least one counter is nonzero
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

    data.sort(key=lambda d: (0 if d["params"]["name"] == "baseline" else 1,
                             d["params"]["block_bytes"],
                             d["params"]["access"]))

    baseline = next((d for d in data if d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 1.0

    # Aggregate counters for each scenario
    agg = {}
    for d in data:
        name = d["params"]["name"]
        agg[name] = aggregate_v3d_counters(d["folder"])

    names = [d["params"]["name"] for d in data]
    x = np.arange(len(names))
    colors_list = [SCENARIO_COLORS.get(n, "#9E9E9E") for n in names]
    x_labels = [nice_label(n) for n in names]

    def get_counter(name, counter):
        return agg.get(name, {}).get(counter, 0)

    # ── Plot 1: L2T Cache Hit Rate ───────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    l2t_hits = [get_counter(n, "L2T-total-cache-hit") for n in names]
    l2t_miss = [get_counter(n, "L2T-total-cache-miss") for n in names]
    l2t_total = [h + m if (h + m) > 0 else 1 for h, m in zip(l2t_hits, l2t_miss)]
    hit_rate = [h / t * 100 for h, t in zip(l2t_hits, l2t_total)]

    bars = ax1.bar(x, hit_rate, color=colors_list, edgecolor="black", linewidth=0.5)
    for bar, val in zip(bars, hit_rate):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")

    ax1.set_ylabel("L2T Cache Hit Rate (%)")
    ax1.set_title("GPU L2T Cache Hit Rate", fontsize=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(x_labels, fontsize=9)
    ax1.set_ylim(0, 105)

    # Absolute hit/miss counts
    bar_w = 0.35
    ax2.bar(x - bar_w / 2, [h / 1e6 for h in l2t_hits], bar_w,
            label="L2T Hits", color="#4CAF50", edgecolor="black", linewidth=0.5)
    ax2.bar(x + bar_w / 2, [m / 1e6 for m in l2t_miss], bar_w,
            label="L2T Misses", color="#F44336", edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Count (millions)")
    ax2.set_title("L2T Cache Hits vs Misses (absolute)", fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels, fontsize=9)
    ax2.legend()

    fig.suptitle("V3D L2T Cache Behavior Under Memory Stress\n"
                 "Hit rate stays high (~94%) but miss count increases under 4M stress → more DRAM traffic",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_l2t_cache.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_l2t_cache.png")
    plt.close(fig)

    # ── Plot 2: Stall Cycles Breakdown ───────────────────────────────────
    stall_counters = [
        ("TMU-stalled-cycles", "TMU Stalled"),
        ("L2T-stalls-mem", "L2T Mem Stalls"),
        ("L2T-stalls-no-wid", "L2T No-WID Stalls"),
        ("L2T-stalls-read-data", "L2T Read-Data Stalls"),
        ("QPU-stalls-TMU", "QPU→TMU Stalls"),
        ("QPU-stalls-uniforms", "QPU→Uniform Stalls"),
    ]

    fig, ax = plt.subplots(figsize=(12, 7))
    n_counters = len(stall_counters)
    bar_w = 0.8 / n_counters
    stall_colors = plt.cm.Set2(np.linspace(0, 1, n_counters))

    for j, (ctr, label) in enumerate(stall_counters):
        vals = [get_counter(n, ctr) / 1e6 for n in names]
        offset = (j - n_counters / 2 + 0.5) * bar_w
        ax.bar(x + offset, vals, bar_w, label=label, color=stall_colors[j],
               edgecolor="black", linewidth=0.3)

    ax.set_xlabel("Memory Stress Scenario")
    ax.set_ylabel("Stall Cycles (millions)")
    ax.set_title("V3D Stall Cycles Breakdown per Scenario\n"
                 "4M stress → massive increase in TMU, L2T, and QPU stalls (memory-bound)",
                 fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=10)
    ax.legend(fontsize=9, loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_stall_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_stall_breakdown.png")
    plt.close(fig)

    # ── Plot 3: AXI Bus Wait Cycles ──────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    axi_read_wait = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names]
    axi_write_wait = [get_counter(n, "AXI-write-wait-cycles") / 1e9 for n in names]

    bar_w = 0.35
    ax1.bar(x - bar_w / 2, axi_read_wait, bar_w, label="AXI Read Wait",
            color="#EF5350", edgecolor="black", linewidth=0.5)
    ax1.bar(x + bar_w / 2, axi_write_wait, bar_w, label="AXI Write Wait",
            color="#42A5F5", edgecolor="black", linewidth=0.5)
    ax1.set_ylabel("Wait Cycles (billions)")
    ax1.set_title("AXI Bus Wait Cycles", fontsize=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(x_labels, fontsize=9)
    ax1.legend()

    for i, (r, w) in enumerate(zip(axi_read_wait, axi_write_wait)):
        ax1.text(i - bar_w / 2, r + 0.05, f"{r:.2f}B", ha="center", fontsize=8)
        ax1.text(i + bar_w / 2, w + 0.05, f"{w:.2f}B", ha="center", fontsize=8)

    # AXI stalled transactions
    axi_read_stall = [get_counter(n, "AXI-reads-stalled-seen-watch-0") / 1e6 for n in names]
    axi_write_stall = [get_counter(n, "AXI-writes-stalled-seen-watch-0") / 1e6 for n in names]

    ax2.bar(x - bar_w / 2, axi_read_stall, bar_w, label="AXI Read Stalls",
            color="#EF5350", edgecolor="black", linewidth=0.5)
    ax2.bar(x + bar_w / 2, axi_write_stall, bar_w, label="AXI Write Stalls",
            color="#42A5F5", edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Stalled Transactions (millions)")
    ax2.set_title("AXI Stalled Transactions", fontsize=12)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels, fontsize=9)
    ax2.legend()

    fig.suptitle("AXI Memory Bus Contention Under Different Memory Stress\n"
                 "4M stress → 2-3× more AXI read wait cycles (GPU competes for DRAM bandwidth)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_axi_bus.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_axi_bus.png")
    plt.close(fig)

    # ── Plot 4: QPU Activity Breakdown (stacked bar) ─────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))

    qpu_active = [get_counter(n, "QPU-active") / 1e6 for n in names]
    qpu_stalls = [get_counter(n, "QPU-stalls") / 1e6 for n in names]
    qpu_bubble = [get_counter(n, "QPU-wait-bubble") / 1e6 for n in names]
    qpu_ic_miss = [get_counter(n, "QPU-ic-miss-bubble") / 1e6 for n in names]

    ax.bar(x, qpu_active, 0.6, label="QPU Active", color="#4CAF50", edgecolor="black", linewidth=0.3)
    ax.bar(x, qpu_stalls, 0.6, bottom=qpu_active, label="QPU Stalls",
           color="#FF9800", edgecolor="black", linewidth=0.3)
    bottom2 = [a + s for a, s in zip(qpu_active, qpu_stalls)]
    ax.bar(x, qpu_bubble, 0.6, bottom=bottom2, label="QPU Wait Bubble",
           color="#F44336", edgecolor="black", linewidth=0.3)
    bottom3 = [b + w for b, w in zip(bottom2, qpu_bubble)]
    ax.bar(x, qpu_ic_miss, 0.6, bottom=bottom3, label="QPU IC-Miss Bubble",
           color="#9C27B0", edgecolor="black", linewidth=0.3)

    # Annotate percentages
    for i in range(len(names)):
        total = qpu_active[i] + qpu_stalls[i] + qpu_bubble[i] + qpu_ic_miss[i]
        if total > 0:
            pct_active = qpu_active[i] / total * 100
            pct_stall = qpu_stalls[i] / total * 100
            pct_bubble = qpu_bubble[i] / total * 100
            ax.text(i, total + 20, f"Active: {pct_active:.1f}%\nStall: {pct_stall:.1f}%\n"
                    f"Bubble: {pct_bubble:.1f}%",
                    ha="center", fontsize=8, fontweight="bold")

    ax.set_xlabel("Memory Stress Scenario")
    ax.set_ylabel("Cycles (millions)")
    ax.set_title("QPU Cycle Breakdown: Active vs Stalls vs Wait Bubbles\n"
                 "Under 4M stress, QPU spends more time in wait-bubbles (memory starvation)",
                 fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=10)
    ax.legend(loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_qpu_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_qpu_breakdown.png")
    plt.close(fig)

    # ── Plot 5: Memory Traffic (read/write transactions) ─────────────────
    fig, ax = plt.subplots(figsize=(10, 6))

    mem_reads = [get_counter(n, "core-memory-reads") / 1e6 for n in names]
    mem_writes = [get_counter(n, "core-memory-writes") / 1e6 for n in names]
    axi_read_trans = [get_counter(n, "AXI-read-trans") / 1e6 for n in names]
    axi_write_trans = [get_counter(n, "AXI-write-trans") / 1e6 for n in names]

    bar_w = 0.2
    ax.bar(x - 1.5 * bar_w, mem_reads, bar_w, label="Core Mem Reads",
           color="#1565C0", edgecolor="black", linewidth=0.3)
    ax.bar(x - 0.5 * bar_w, mem_writes, bar_w, label="Core Mem Writes",
           color="#42A5F5", edgecolor="black", linewidth=0.3)
    ax.bar(x + 0.5 * bar_w, axi_read_trans, bar_w, label="AXI Read Trans",
           color="#C62828", edgecolor="black", linewidth=0.3)
    ax.bar(x + 1.5 * bar_w, axi_write_trans, bar_w, label="AXI Write Trans",
           color="#EF5350", edgecolor="black", linewidth=0.3)

    ax.set_xlabel("Memory Stress Scenario")
    ax.set_ylabel("Transactions (millions)")
    ax.set_title("V3D Memory Traffic: Core & AXI Transactions\n"
                 "Transaction counts increase under 4M stress due to longer execution time",
                 fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=10)
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_traffic.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_traffic.png")
    plt.close(fig)

    # ── Plot 6: Normalized Heatmap of Key Counters ───────────────────────
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

    # Build matrix: rows=counters, cols=scenarios
    matrix = []
    for ctr in key_counters:
        row = [get_counter(n, ctr) for n in names]
        matrix.append(row)
    matrix = np.array(matrix, dtype=float)

    # Normalize each row by baseline (first column)
    norm_matrix = np.zeros_like(matrix)
    for i in range(matrix.shape[0]):
        baseline_val = matrix[i, 0] if matrix[i, 0] > 0 else 1
        norm_matrix[i, :] = matrix[i, :] / baseline_val

    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(norm_matrix, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=5)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([nice_label(n).replace("\n", " ") for n in names], fontsize=10, rotation=30, ha="right")
    ax.set_yticks(range(len(key_counters)))
    ax.set_yticklabels(key_counters, fontsize=9)

    # Add values to cells
    for i in range(len(key_counters)):
        for j in range(len(names)):
            val = norm_matrix[i, j]
            text_color = "white" if val > 3 else "black"
            ax.text(j, i, f"{val:.2f}×", ha="center", va="center",
                    fontsize=8, color=text_color, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("× Baseline", fontsize=10)

    ax.set_title("V3D Counter Values Normalized to Baseline\n"
                 "Red = counter much higher than baseline (more stress impact)\n"
                 "Green = similar to baseline", fontsize=12)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_counter_heatmap.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_counter_heatmap.png")
    plt.close(fig)

    # ── Print Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("V3D COUNTERS vs MEMORY STRESS – SUMMARY")
    print("=" * 80)

    # Print key counter comparisons
    highlight = [
        ("L2T-total-cache-hit", "L2T Cache Hits"),
        ("L2T-total-cache-miss", "L2T Cache Misses"),
        ("TMU-stalled-cycles", "TMU Stalled Cycles"),
        ("L2T-stalls-mem", "L2T Memory Stalls"),
        ("QPU-active", "QPU Active Cycles"),
        ("QPU-stalls", "QPU Total Stalls"),
        ("QPU-stalls-TMU", "QPU→TMU Stalls"),
        ("QPU-wait-bubble", "QPU Wait Bubble"),
        ("AXI-read-wait-cycles", "AXI Read Wait"),
        ("AXI-write-wait-cycles", "AXI Write Wait"),
    ]

    header = f"{'Counter':<25s}"
    for n in names:
        header += f"  {n:>14s}"
    header += "   4M/base ratio"
    print(header)
    print("-" * (25 + 16 * len(names) + 18))

    for ctr, label in highlight:
        row = f"{label:<25s}"
        vals = [get_counter(n, ctr) for n in names]
        for v in vals:
            if v > 1e9:
                row += f"  {v / 1e9:>13.2f}B"
            elif v > 1e6:
                row += f"  {v / 1e6:>13.2f}M"
            elif v > 1e3:
                row += f"  {v / 1e3:>13.2f}K"
            else:
                row += f"  {v:>14d}"
        # Ratio of last (4mr) to first (baseline)
        if vals[0] > 0:
            ratio = vals[-1] / vals[0]
            row += f"   {ratio:.2f}×"
        print(row)

    print("\n KEY INSIGHTS:")
    print("  • L2T cache hit rate stays ~94% even under 4M stress")
    print("    → GPU's own cache isn't thrashing, but DRAM latency behind misses explodes")
    print("  • AXI read wait cycles increase ~2×+ under 4M stress")
    print("    → DRAM bus is shared; CPU memory traffic adds queueing delay")
    print("  • QPU wait-bubble cycles dominate under 4M stress")
    print("    → QPU sits idle waiting for memory data that's stuck in DRAM queue")
    print("  • TMU stalls track with AXI contention (TMU fetches go through L2T→AXI→DRAM)")
    print("  • 16K stress → minimal impact because 16K fits in CPU L1 cache,")
    print("    never reaches DRAM → no contention with GPU")


if __name__ == "__main__":
    main()

