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
  - Correlation with Compute Latency and Dispatch Latency (E2E - Compute)

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
  7. v3d_mem_hardware_vs_dispatch.png:
     Hardware AXI wait cycles & L2T stalls vs Compute and Dispatch Latencies across EVERY scenario.
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
    block_b = p.get("block_bytes", 0)
    name = p.get("name", "")
    return (cat_rank, block_b, name)


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

    # Sort deterministically: all scenarios included!
    data.sort(key=sort_key)

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 4120.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["dispatch_latency_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    # Aggregate counters for each scenario
    agg = {}
    for d in data:
        name = d["params"]["name"]
        agg[name] = aggregate_v3d_counters(d["folder"])

    names = [d["params"]["name"] for d in data]
    x = np.arange(len(names))
    colors_list = [scenario_color(d["params"]) for d in data]
    x_labels = [nice_label(n, d["params"]) for n, d in zip(names, data)]

    def get_counter(name, counter):
        return agg.get(name, {}).get(counter, 0)

    # ── Plot 1: L2T Cache Hit Rate (EVERY Scenario) ──────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    l2t_hits = [get_counter(n, "L2T-total-cache-hit") for n in names]
    l2t_miss = [get_counter(n, "L2T-total-cache-miss") for n in names]
    l2t_total = [h + m if (h + m) > 0 else 1 for h, m in zip(l2t_hits, l2t_miss)]
    hit_rate = [h / t * 100 for h, t in zip(l2t_hits, l2t_total)]

    bars = ax1.bar(x, hit_rate, color=colors_list, edgecolor="black", linewidth=0.5)
    for bar, val in zip(bars, hit_rate):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                 f"{val:.1f}%", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax1.set_ylabel("L2T Cache Hit Rate (%)")
    ax1.set_title("GPU L2T Cache Hit Rate Across All Scenarios", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax1.set_ylim(0, 105)

    # Absolute hit/miss counts
    bar_w = 0.35
    ax2.bar(x - bar_w / 2, [h / 1e6 for h in l2t_hits], bar_w,
            label="L2T Hits", color="#4CAF50", edgecolor="black", linewidth=0.5)
    ax2.bar(x + bar_w / 2, [m / 1e6 for m in l2t_miss], bar_w,
            label="L2T Misses", color="#F44336", edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Count (millions)")
    ax2.set_title("L2T Cache Hits vs Misses (absolute)", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax2.legend()

    fig.suptitle("V3D L2T Cache Behavior Across ALL Interference Parameters", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_l2t_cache.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_l2t_cache.png")
    plt.close(fig)

    # ── Plot 2: Stall Cycles Breakdown (EVERY Scenario) ──────────────────
    stall_counters = [
        ("TMU-stalled-cycles", "TMU Stalled"),
        ("L2T-stalls-mem", "L2T Mem Stalls"),
        ("L2T-stalls-no-wid", "L2T No-WID Stalls"),
        ("L2T-stalls-read-data", "L2T Read-Data Stalls"),
        ("QPU-stalls-TMU", "QPU→TMU Stalls"),
        ("QPU-stalls-uniforms", "QPU→Uniform Stalls"),
    ]

    fig, ax = plt.subplots(figsize=(16, 6.5))
    n_counters = len(stall_counters)
    b_w = 0.8 / n_counters
    stall_colors = plt.cm.Set2(np.linspace(0, 1, n_counters))

    for j, (ctr, label) in enumerate(stall_counters):
        vals = [get_counter(n, ctr) / 1e6 for n in names]
        offset = (j - n_counters / 2 + 0.5) * b_w
        ax.bar(x + offset, vals, b_w, label=label, color=stall_colors[j],
               edgecolor="black", linewidth=0.3)

    ax.set_xlabel("Interference Scenario (All Parameters)")
    ax.set_ylabel("Stall Cycles (millions)")
    ax.set_title("V3D Pipeline Stall Cycles Breakdown Across ALL Parameters", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax.legend(fontsize=8.5, loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_stall_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_stall_breakdown.png")
    plt.close(fig)

    # ── Plot 3: AXI Bus Wait Cycles (EVERY Scenario) ─────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    axi_read_wait = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names]
    axi_write_wait = [get_counter(n, "AXI-write-wait-cycles") / 1e9 for n in names]

    bar_w = 0.35
    ax1.bar(x - bar_w / 2, axi_read_wait, bar_w, label="AXI Read Wait",
            color="#EF5350", edgecolor="black", linewidth=0.5)
    ax1.bar(x + bar_w / 2, axi_write_wait, bar_w, label="AXI Write Wait",
            color="#42A5F5", edgecolor="black", linewidth=0.5)
    ax1.set_ylabel("Wait Cycles (billions)")
    ax1.set_title("AXI Bus Wait Cycles (All Scenarios)", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax1.legend()

    for i, (r, w) in enumerate(zip(axi_read_wait, axi_write_wait)):
        if r > 0.1:
            ax1.text(i - bar_w / 2, r + 0.1, f"{r:.1f}B", ha="center", fontsize=6.5)
        if w > 0.1:
            ax1.text(i + bar_w / 2, w + 0.1, f"{w:.1f}B", ha="center", fontsize=6.5)

    # AXI stalled transactions
    axi_read_stall = [get_counter(n, "AXI-reads-stalled-seen-watch-0") / 1e6 for n in names]
    axi_write_stall = [get_counter(n, "AXI-writes-stalled-seen-watch-0") / 1e6 for n in names]

    ax2.bar(x - bar_w / 2, axi_read_stall, bar_w, label="AXI Read Stalls",
            color="#EF5350", edgecolor="black", linewidth=0.5)
    ax2.bar(x + bar_w / 2, axi_write_stall, bar_w, label="AXI Write Stalls",
            color="#42A5F5", edgecolor="black", linewidth=0.5)
    ax2.set_ylabel("Stalled Transactions (millions)")
    ax2.set_title("AXI Stalled Transactions", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax2.legend()

    fig.suptitle("AXI Memory Bus Contention: Hardware Wait Cycles Across ALL Parameters",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_axi_bus.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_axi_bus.png")
    plt.close(fig)

    # ── Plot 4: QPU Cycle Breakdown (EVERY Scenario) ─────────────────────
    fig, ax = plt.subplots(figsize=(15, 6))

    qpu_active = [get_counter(n, "QPU-active") / 1e6 for n in names]
    qpu_stalls = [get_counter(n, "QPU-stalls") / 1e6 for n in names]
    qpu_bubble = [get_counter(n, "QPU-wait-bubble") / 1e6 for n in names]
    qpu_ic_miss = [get_counter(n, "QPU-ic-miss-bubble") / 1e6 for n in names]

    ax.bar(x, qpu_active, 0.55, label="QPU Active", color="#4CAF50", edgecolor="black", linewidth=0.3)
    ax.bar(x, qpu_stalls, 0.55, bottom=qpu_active, label="QPU Stalls",
           color="#FF9800", edgecolor="black", linewidth=0.3)
    bottom2 = [a + s for a, s in zip(qpu_active, qpu_stalls)]
    ax.bar(x, qpu_bubble, 0.55, bottom=bottom2, label="QPU Wait Bubble",
           color="#F44336", edgecolor="black", linewidth=0.3)
    bottom3 = [b + w for b, w in zip(bottom2, qpu_bubble)]
    ax.bar(x, qpu_ic_miss, 0.55, bottom=bottom3, label="QPU IC-Miss Bubble",
           color="#9C27B0", edgecolor="black", linewidth=0.3)

    for i in range(len(names)):
        total = qpu_active[i] + qpu_stalls[i] + qpu_bubble[i] + qpu_ic_miss[i]
        if total > 0:
            pct_bubble = qpu_bubble[i] / total * 100
            ax.text(i, total + 30, f"{pct_bubble:.0f}%",
                    ha="center", fontsize=7, fontweight="bold")

    ax.set_xlabel("Interference Scenario (All Parameters)")
    ax.set_ylabel("Cycles (millions)")
    ax.set_title("QPU Execution Breakdown: Active vs Stalls vs Wait Bubbles Across ALL Scenarios", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax.legend(loc="upper left")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_qpu_breakdown.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_qpu_breakdown.png")
    plt.close(fig)

    # ── Plot 5: Memory Traffic (EVERY Scenario) ──────────────────────────
    fig, ax = plt.subplots(figsize=(15, 6))

    mem_reads = [get_counter(n, "core-memory-reads") / 1e6 for n in names]
    mem_writes = [get_counter(n, "core-memory-writes") / 1e6 for n in names]
    axi_read_trans = [get_counter(n, "AXI-read-trans") / 1e6 for n in names]
    axi_write_trans = [get_counter(n, "AXI-write-trans") / 1e6 for n in names]

    b_w = 0.2
    ax.bar(x - 1.5 * b_w, mem_reads, b_w, label="Core Mem Reads", color="#1565C0", edgecolor="black", linewidth=0.3)
    ax.bar(x - 0.5 * b_w, mem_writes, b_w, label="Core Mem Writes", color="#42A5F5", edgecolor="black", linewidth=0.3)
    ax.bar(x + 0.5 * b_w, axi_read_trans, b_w, label="AXI Read Trans", color="#C62828", edgecolor="black", linewidth=0.3)
    ax.bar(x + 1.5 * b_w, axi_write_trans, b_w, label="AXI Write Trans", color="#EF5350", edgecolor="black", linewidth=0.3)

    ax.set_xlabel("Interference Scenario (All Parameters)")
    ax.set_ylabel("Transactions (millions)")
    ax.set_title("V3D Memory Traffic: Core & AXI Transactions Across ALL Parameters", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=7.5, rotation=25, ha="right")
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_traffic.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_traffic.png")
    plt.close(fig)

    # ── Plot 6: Normalized Heatmap of Key Counters (EVERY Scenario) ──────
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

    matrix = []
    for ctr in key_counters:
        row = [get_counter(n, ctr) for n in names]
        matrix.append(row)
    matrix = np.array(matrix, dtype=float)

    # Normalize each row by baseline
    norm_matrix = np.zeros_like(matrix)
    for i in range(matrix.shape[0]):
        base_val = matrix[i, 0] if matrix[i, 0] > 0 else 1
        norm_matrix[i, :] = matrix[i, :] / base_val

    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(norm_matrix, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=6)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([nice_label(n, d["params"]).replace("\n", " ") for n, d in zip(names, data)],
                       fontsize=8, rotation=30, ha="right")
    ax.set_yticks(range(len(key_counters)))
    ax.set_yticklabels(key_counters, fontsize=9)

    for i in range(len(key_counters)):
        for j in range(len(names)):
            val = norm_matrix[i, j]
            text_color = "white" if val > 4 else "black"
            ax.text(j, i, f"{val:.1f}×", ha="center", va="center",
                    fontsize=7, color=text_color, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("× Baseline", fontsize=10)
    ax.set_title("V3D Hardware Counters Normalized to Baseline Across EVERY Parameter", fontsize=13)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_counter_heatmap.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_counter_heatmap.png")
    plt.close(fig)

    # ── Plot 7: Hardware Contention vs Compute & Dispatch Latency (EVERY Scenario) ─
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    axi_waits_b = [get_counter(n, "AXI-read-wait-cycles") / 1e9 for n in names]
    comp_lats = [d["gpu"]["compute_ms"] for d in data]
    disp_lats = [d["gpu"]["dispatch_latency_ms"] for d in data]

    # Left: AXI Read Wait Cycles vs Compute Latency
    for n, c, w, comp in zip(names, colors_list, axi_waits_b, comp_lats):
        ax1.scatter(w, comp, s=160, color=c, edgecolors="black", zorder=4)
        ax1.annotate(f" {n}", (w, comp), fontsize=7.5, fontweight="bold")

    ax1.set_xlabel("AXI Read Wait Cycles (billions)")
    ax1.set_ylabel("Compute Latency (ms)")
    ax1.set_title("AXI Read Wait Cycles vs GPU Compute Latency", fontsize=11)

    # Right: AXI Read Wait Cycles vs Dispatch Latency (E2E - Compute)
    for n, c, w, disp in zip(names, colors_list, axi_waits_b, disp_lats):
        ax2.scatter(w, disp, s=160, color=c, edgecolors="black", zorder=4)
        ax2.annotate(f" {n}\n ({disp:.2f}ms)", (w, disp), fontsize=7.5, fontweight="bold")

    ax2.set_xlabel("AXI Read Wait Cycles (billions)")
    ax2.set_ylabel("Dispatch Latency (ms) = E2E - Compute")
    ax2.set_title("AXI Read Wait Cycles vs CPU Dispatch Latency", fontsize=11)

    fig.suptitle("Interconnect Contention: Impact on GPU Kernel vs CPU Dispatch Overhead (All Parameters)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "v3d_mem_hardware_vs_dispatch.png"), dpi=150)
    print(f"  → {PLOT_DIR}/v3d_mem_hardware_vs_dispatch.png")
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
    r_disp = f"{'Dispatch Lat (ms)':<22s}"
    for d in data:
        r_comp += f"  {d['gpu']['compute_ms']:>9.0f}"
        r_disp += f"  {d['gpu']['dispatch_latency_ms']:>9.3f}"
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
