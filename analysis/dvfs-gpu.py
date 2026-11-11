#!/usr/bin/env python3
"""
dvfs-gpu.py  ─  DVFS Parameters vs GPU Execution & E2E-GPU Residual (All Scenarios)
===================================================================================
Correlates Dynamic Voltage and Frequency Scaling (DVFS) state with
GPU task latency (Compute vs E2E-GPU Residual) across EVERY parameter scenario:
  - Baseline
  - CPU-side contentions (mutex, prime, threads)
  - Page-fault stressors (stress-ng fault/mmap)
  - Cache-resident & cache-evicting memory stressors
  - DRAM streaming & random access
  - Coherence & thread sweep

Analyzes:
  - CPU frequency, ARM PLL, V3D clock during GPU activity
  - Temperature progression under stress
  - Throttling state correlation
  - Impact on GPU Compute Latency vs E2E-GPU Residual (E2E - GPU timer)

Plots generated (saved to analysis/plots/):
  1. dvfs_gpu_timeline.png:
     DVFS timeline per scenario (CPU freq, V3D clock, temperature).
  2. dvfs_gpu_v3d_clock_dist.png:
     V3D clock distribution across EVERY scenario.
  3. dvfs_gpu_temp_vs_latency.png:
     Temperature vs Compute Latency and E2E-GPU Residual across EVERY scenario.
  4. dvfs_gpu_summary_bars.png:
     5-panel summary: CPU Freq, V3D Clock, Max Temp, Compute Latency, E2E-GPU Residual.
  5. dvfs_gpu_temperature_ramp.png:
     Thermal ramp progression over experiment timeline.
"""

import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import (
    load_all,
    load_dvfs,
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


def get_gpu_active_dvfs(dvfs_df):
    """Filter DVFS samples to only GPU=active window."""
    if dvfs_df.empty or "gpu_state" not in dvfs_df.columns:
        return pd.DataFrame()
    return dvfs_df[dvfs_df["gpu_state"] == "active"].copy()


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

    names = [d["params"]["name"] for d in data]
    colors_list = [scenario_color(d["params"]) for d in data]

    # Split data into Part 1 (CPU & Cache <= 4 MiB) and Part 2 (DRAM, Sweeps, System >= 8 MiB)
    data_p1, data_p2 = split_data_parts(data)

    bar_w = 0.38
    x1, ticks1, labels1 = compute_pair_positions(data_p1, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)
    x2, ticks2, labels2 = compute_pair_positions(data_p2, bar_width=bar_w, pair_gap=0.06, group_gap=0.55)

    colors1 = [scenario_color(d["params"]) for d in data_p1]
    colors2 = [scenario_color(d["params"]) for d in data_p2]

    # Legend elements for Read vs Write distinction
    legend_read = Patch(facecolor="#9E9E9E", edgecolor="black", label="Read (solid)")
    legend_write = Patch(facecolor="#9E9E9E", edgecolor="black", hatch="//", label="Write (hatched //)")

    # ── Plot 1: DVFS Timeline per Scenario (subplots) ────────────────────
    fig, axes = plt.subplots(len(data), 1, figsize=(14, 3.2 * len(data)), sharex=False)
    if len(data) == 1:
        axes = [axes]

    for ax, d in zip(axes, data):
        dvfs = d["dvfs"]
        name = d["params"]["name"]
        color = scenario_color(d["params"])

        if dvfs.empty:
            ax.text(0.5, 0.5, f"{name}: No DVFS data", transform=ax.transAxes,
                    ha="center", fontsize=13)
            continue

        elapsed = dvfs["elapsed_s"].values
        cpu_mhz = dvfs["cpu_khz"].values / 1000.0
        v3d_mhz = dvfs["v3d_hz"].values / 1e6
        temp = dvfs["temp_c"].values

        # CPU freq
        ax.plot(elapsed, cpu_mhz, "s-", color=color, label="CPU (MHz)", markersize=3, linewidth=1.4)
        # V3D freq
        ax.plot(elapsed, v3d_mhz, "^-", color="purple", label="V3D (MHz)", markersize=4, linewidth=1.4)

        # Temperature on twin axis
        ax2 = ax.twinx()
        ax2.plot(elapsed, temp, "o-", color="orange", label="Temp (°C)", markersize=3, linewidth=1, alpha=0.8)
        ax2.set_ylabel("Temp (°C)", color="orange")
        ax2.tick_params(axis="y", labelcolor="orange")

        # Mark GPU active region
        active = dvfs[dvfs["gpu_state"] == "active"]
        if not active.empty:
            t_start = active["elapsed_s"].min()
            t_end = active["elapsed_s"].max()
            ax.axvspan(t_start, t_end, alpha=0.1, color="green", label="GPU active")

        comp_lat = d["gpu"]["compute_ms"]
        disp_lat = d["gpu"]["e2e_minus_gpu_ms"]
        ax.set_title(f"{name} ({d['params']['category']})  –  Compute: {comp_lat:.0f} ms | Residual: {disp_lat:.3f} ms",
                     fontsize=10.5, fontweight="bold")
        ax.set_ylabel("Frequency (MHz)")
        ax.legend(loc="upper left", fontsize=8)
        ax2.legend(loc="upper right", fontsize=8)

    axes[-1].set_xlabel("Elapsed Time (seconds)")
    fig.suptitle("DVFS Timeline: CPU Freq, V3D Clock, Temperature per Scenario (All Parameters)",
                 fontsize=14, fontweight="bold", y=1.01)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_timeline.png"), dpi=150, bbox_inches="tight")
    print(f"  → {PLOT_DIR}/dvfs_gpu_timeline.png")
    plt.close(fig)

    # Helpers to extract DVFS metrics
    def extract_dvfs_metrics(dataset):
        mean_c, min_c, max_c = [], [], []
        cpu_f, v3d_f, avg_t, max_t = [], [], [], []
        comp, disp = [], []
        for d in dataset:
            dvfs = d["dvfs"]
            active = get_gpu_active_dvfs(dvfs)
            if active.empty:
                v3d_vals = dvfs[dvfs["v3d_hz"] > 0]["v3d_hz"].values / 1e6 if not dvfs.empty else [960.0]
                c_khz = dvfs["cpu_khz"].mean() / 1000.0 if not dvfs.empty else 2400.0
                v_hz = dvfs["v3d_hz"].mean() / 1e6 if not dvfs.empty else 960.0
                a_t = dvfs["temp_c"].mean() if not dvfs.empty else 50.0
                m_t = dvfs["temp_c"].max() if not dvfs.empty else 50.0
            else:
                v3d_vals = active["v3d_hz"].values / 1e6
                c_khz = active["cpu_khz"].mean() / 1000.0
                v_hz = active["v3d_hz"].mean() / 1e6
                a_t = active["temp_c"].mean()
                m_t = active["temp_c"].max()
            if len(v3d_vals) == 0:
                v3d_vals = [960.0]
            mean_c.append(float(np.mean(v3d_vals)))
            min_c.append(float(np.min(v3d_vals)))
            max_c.append(float(np.max(v3d_vals)))
            cpu_f.append(float(c_khz))
            v3d_f.append(float(v_hz))
            avg_t.append(float(a_t))
            max_t.append(float(m_t))
            comp.append(float(d["gpu"]["compute_ms"]))
            disp.append(float(d["gpu"]["e2e_minus_gpu_ms"]))
        return (
            np.array(mean_c), np.array(min_c), np.array(max_c),
            np.array(cpu_f), np.array(v3d_f), np.array(avg_t), np.array(max_t),
            np.array(comp), np.array(disp)
        )

    (mean_c1, min_c1, max_c1, cpu_f1, v3d_f1, avg_t1, max_t1, comp1, disp1) = extract_dvfs_metrics(data_p1)
    (mean_c2, min_c2, max_c2, cpu_f2, v3d_f2, avg_t2, max_t2, comp2, disp2) = extract_dvfs_metrics(data_p2)

    # ── Plot 2: V3D Clock Stability Across EVERY Scenario (Split: Part 1 & Part 2) ─────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 10))

    # Panel 1: Part 1
    yerr_lower1 = np.maximum(mean_c1 - min_c1, 0)
    yerr_upper1 = np.maximum(max_c1 - mean_c1, 0)
    b_clk1 = ax1.bar(x1, mean_c1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6,
                     yerr=[yerr_lower1, yerr_upper1], capsize=3, error_kw=dict(lw=1.0, capthick=1.0, color="black"))
    for bar, d, m_clk in zip(b_clk1, data_p1, mean_c1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                 f"{m_clk:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.set_ylabel("V3D Clock (MHz)", fontsize=10)
    ax1.set_ylim(0, 1150)
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — V3D Clock Stability", fontsize=11, fontweight="bold")
    h_clk1, _ = ax1.get_legend_handles_labels()
    h_clk1.extend([legend_read, legend_write])
    ax1.legend(handles=h_clk1, loc="upper left", fontsize=8)

    # Panel 2: Part 2
    yerr_lower2 = np.maximum(mean_c2 - min_c2, 0)
    yerr_upper2 = np.maximum(max_c2 - mean_c2, 0)
    b_clk2 = ax2.bar(x2, mean_c2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6,
                     yerr=[yerr_lower2, yerr_upper2], capsize=3, error_kw=dict(lw=1.0, capthick=1.0, color="black"))
    for bar, d, m_clk in zip(b_clk2, data_p2, mean_c2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                 f"{m_clk:.0f}", ha="center", va="bottom", fontsize=7, fontweight="bold", rotation=90)
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.set_ylabel("V3D Clock (MHz)", fontsize=10)
    ax2.set_ylim(0, 1150)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults (8 MiB to 256 MiB+) — V3D Clock Stability", fontsize=11, fontweight="bold")
    h_clk2, _ = ax2.get_legend_handles_labels()
    h_clk2.extend([legend_read, legend_write])
    ax2.legend(handles=h_clk2, loc="upper left", fontsize=8)

    fig.suptitle("V3D GPU Clock Frequency (Mean with Min-Max Range) (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_v3d_clock_dist.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_v3d_clock_dist.png")
    plt.close(fig)

    # ── Plot 3: Temperature vs Compute Latency and Residual (Split: Part 1 & Part 2) ──
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 11))

    # Panel 3a: Part 1
    ax1_twin = ax1.twinx()
    temp_err_upper1 = np.maximum(max_t1 - avg_t1, 0)
    b_t1 = ax1.bar(x1, avg_t1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.6,
                   yerr=[np.zeros(len(avg_t1)), temp_err_upper1], capsize=2.5,
                   error_kw=dict(lw=0.8, color="black"), label="Avg Temp (°C, cap=max)")
    for bar, d in zip(b_t1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c1 = ax1_twin.plot(x1, comp1, "ro-", markersize=5.5, linewidth=1.5, label="Compute Latency (ms)")
    l_d1 = ax1_twin.plot(x1, disp1, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")
    ax1.set_ylabel("SoC Temperature (°C)", color="black", fontsize=10)
    ax1_twin.set_ylabel("Latency (ms)", color="black", fontsize=10)
    ax1.set_title("Part 1: CPU Contention & Cache Hierarchy Stressors (Baseline to 4 MiB) — SoC Temp vs Latencies", fontsize=11, fontweight="bold")
    ax1.set_xticks(ticks1)
    ax1.set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    ax1.set_xlim(x1[0] - 1.0, x1[-1] + 1.0)
    ax1.set_ylim(0, 95)
    lines_t1 = [b_t1, l_c1[0], l_d1[0], legend_read, legend_write]
    ax1.legend(lines_t1, ["Avg Temp (°C)", "Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    # Panel 3b: Part 2
    ax2_twin = ax2.twinx()
    temp_err_upper2 = np.maximum(max_t2 - avg_t2, 0)
    b_t2 = ax2.bar(x2, avg_t2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.6,
                   yerr=[np.zeros(len(avg_t2)), temp_err_upper2], capsize=2.5,
                   error_kw=dict(lw=0.8, color="black"), label="Avg Temp (°C, cap=max)")
    for bar, d in zip(b_t2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    l_c2 = ax2_twin.plot(x2, comp2, "ro-", markersize=5.5, linewidth=1.5, label="Compute Latency (ms)")
    l_d2 = ax2_twin.plot(x2, disp2, "s--", color="#D84315", markersize=5.5, linewidth=1.5, label="E2E-GPU Residual (ms)")
    ax2.set_ylabel("SoC Temperature (°C)", color="black", fontsize=10)
    ax2_twin.set_ylabel("Latency (ms)", color="black", fontsize=10)
    ax2.set_title("Part 2: DRAM Bandwidth, Concurrency Sweeps, Coherence & Page Faults — SoC Temp vs Latencies", fontsize=11, fontweight="bold")
    ax2.set_xticks(ticks2)
    ax2.set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    ax2.set_xlim(x2[0] - 1.0, x2[-1] + 1.0)
    ax2.set_ylim(0, 95)
    lines_t2 = [b_t2, l_c2[0], l_d2[0], legend_read, legend_write]
    ax2.legend(lines_t2, ["Avg Temp (°C)", "Compute Latency (ms)", "E2E-GPU Residual (ms)", "Read (solid)", "Write (hatched //)"], loc="upper left", fontsize=8)

    fig.suptitle("SoC Thermal State vs Compute & E2E-GPU Residuals (Split: Part 1 vs Part 2)", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_temp_vs_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_temp_vs_latency.png")
    plt.close(fig)

    # ── Plot 4: 5x2 Comparative DVFS Summary Bar Chart (Split: Part 1 & Part 2) ────────
    fig, axes = plt.subplots(5, 2, figsize=(20, 16), sharex="col")

    # Column 0: Part 1
    # 4a: Avg CPU Freq
    b_cpu1 = axes[0, 0].bar(x1, cpu_f1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_cpu1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[0, 0].set_title("Part 1: Avg CPU Freq (MHz) [GPU active]", fontsize=10, fontweight="bold")
    axes[0, 0].set_ylabel("MHz")
    axes[0, 0].set_ylim(0, 2600)

    # 4b: Avg V3D Freq
    b_v3d1 = axes[1, 0].bar(x1, v3d_f1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_v3d1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[1, 0].set_title("Part 1: Avg V3D Clock (MHz) [GPU active]", fontsize=10, fontweight="bold")
    axes[1, 0].set_ylabel("MHz")
    axes[1, 0].set_ylim(0, 1150)

    # 4c: Max Temp
    b_tmp1 = axes[2, 0].bar(x1, max_t1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_tmp1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[2, 0].set_title("Part 1: Max Temperature (°C) [peak]", fontsize=10, fontweight="bold")
    axes[2, 0].set_ylabel("°C")
    axes[2, 0].set_ylim(0, 95)

    # 4d: GPU Compute Latency
    b_cmp1 = axes[3, 0].bar(x1, comp1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_cmp1, data_p1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[3, 0].set_title("Part 1: GPU Compute Latency (ms)", fontsize=10, fontweight="bold")
    axes[3, 0].set_ylabel("ms")

    # 4e: E2E-GPU Residual
    b_dsp1 = axes[4, 0].bar(x1, disp1, width=bar_w, color=colors1, edgecolor="black", linewidth=0.5)
    for bar, d, v in zip(b_dsp1, data_p1, disp1):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        axes[4, 0].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, f"{v:.2f}", ha="center", va="bottom", fontsize=6, fontweight="bold", rotation=90)
    axes[4, 0].set_title("Part 1: E2E-GPU Residual (ms)", fontsize=10, fontweight="bold")
    axes[4, 0].set_ylabel("ms")
    axes[4, 0].set_xticks(ticks1)
    axes[4, 0].set_xticklabels(labels1, fontsize=8, rotation=45, ha="right")
    axes[4, 0].set_xlim(x1[0] - 1.0, x1[-1] + 1.0)

    # Column 1: Part 2
    # 4a: Avg CPU Freq
    b_cpu2 = axes[0, 1].bar(x2, cpu_f2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_cpu2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[0, 1].set_title("Part 2: Avg CPU Freq (MHz) [GPU active]", fontsize=10, fontweight="bold")
    axes[0, 1].set_ylabel("MHz")
    axes[0, 1].set_ylim(0, 2600)

    # 4b: Avg V3D Freq
    b_v3d2 = axes[1, 1].bar(x2, v3d_f2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_v3d2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[1, 1].set_title("Part 2: Avg V3D Clock (MHz) [GPU active]", fontsize=10, fontweight="bold")
    axes[1, 1].set_ylabel("MHz")
    axes[1, 1].set_ylim(0, 1150)

    # 4c: Max Temp
    b_tmp2 = axes[2, 1].bar(x2, max_t2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_tmp2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[2, 1].set_title("Part 2: Max Temperature (°C) [peak]", fontsize=10, fontweight="bold")
    axes[2, 1].set_ylabel("°C")
    axes[2, 1].set_ylim(0, 95)

    # 4d: GPU Compute Latency
    b_cmp2 = axes[3, 1].bar(x2, comp2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d in zip(b_cmp2, data_p2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
    axes[3, 1].set_title("Part 2: GPU Compute Latency (ms)", fontsize=10, fontweight="bold")
    axes[3, 1].set_ylabel("ms")

    # 4e: E2E-GPU Residual
    b_dsp2 = axes[4, 1].bar(x2, disp2, width=bar_w, color=colors2, edgecolor="black", linewidth=0.5)
    for bar, d, v in zip(b_dsp2, data_p2, disp2):
        if d["params"].get("oper") == "write":
            bar.set_hatch("//")
        axes[4, 1].text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, f"{v:.2f}", ha="center", va="bottom", fontsize=6, fontweight="bold", rotation=90)
    axes[4, 1].set_title("Part 2: E2E-GPU Residual (ms)", fontsize=10, fontweight="bold")
    axes[4, 1].set_ylabel("ms")
    axes[4, 1].set_xticks(ticks2)
    axes[4, 1].set_xticklabels(labels2, fontsize=8, rotation=45, ha="right")
    axes[4, 1].set_xlim(x2[0] - 1.0, x2[-1] + 1.0)

    fig.suptitle("DVFS State vs GPU Compute Latency vs E2E-GPU Residual (Split: Part 1 vs Part 2)",
                 fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_summary_bars.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_summary_bars.png")
    plt.close(fig)

    # ── Plot 5: Temperature Ramp Progression ─────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 6))
    for d in data:
        dvfs = d["dvfs"]
        if dvfs.empty:
            continue
        name = d["params"]["name"]
        color = scenario_color(d["params"])
        ax.plot(dvfs["elapsed_s"], dvfs["temp_c"], "o-", color=color,
                label=f"{name} ({d['params']['category']})",
                markersize=3, linewidth=1.4)

    ax.set_xlabel("Elapsed Time (seconds)")
    ax.set_ylabel("SoC Temperature (°C)")
    ax.set_title("Thermal Ramp During Experiment Across All Scenarios", fontsize=12)
    ax.legend(fontsize=7.5, loc="best", ncol=2)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_temperature_ramp.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_temperature_ramp.png")
    plt.close(fig)

    # ── Print Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 115)
    print("DVFS vs GPU LATENCY (COMPUTE & E2E-GPU RESIDUAL) ACROSS ALL PARAMETERS – SUMMARY")
    print("=" * 115)
    print(f"{'Scenario':<14s} {'Category':<15s} {'CPU(MHz)':>10s} {'V3D(MHz)':>10s} {'MaxTemp':>8s} "
          f"{'E2E(ms)':>10s} {'Comp(ms)':>10s} {'Disp(ms)':>10s} {'CompDeg':>9s} {'DispDeg':>9s}")
    print("-" * 115)
    avg_cpu = np.concatenate([cpu_f1, cpu_f2])
    avg_v3d = np.concatenate([v3d_f1, v3d_f2])
    max_temps = np.concatenate([max_t1, max_t2])
    for d, cpu, v3d, temp in zip(data_p1 + data_p2, avg_cpu, avg_v3d, max_temps):
        p = d["params"]
        g = d["gpu"]
        e2e = g["e2e_ms"]
        comp = g["compute_ms"]
        disp = g["e2e_minus_gpu_ms"]
        c_deg = comp / base_comp
        d_deg = disp / base_disp if base_disp > 0 else 1.0

        print(f"{p['name']:<14s} {p['category']:<15s} {cpu:>10.0f} {v3d:>10.1f} {temp:>7.1f}° "
              f"{e2e:>10.1f} {comp:>10.1f} {disp:>10.3f} {c_deg:>8.2f}× {d_deg:>8.2f}×")


if __name__ == "__main__":
    main()