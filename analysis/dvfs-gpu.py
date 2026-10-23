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

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import load_all, load_dvfs, DATA_DIR

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

    # Sort deterministically: all scenarios included!
    data.sort(key=sort_key)

    baseline = next((d for d in data if d["params"]["category"] == "baseline" or d["params"]["name"] == "baseline"), None)
    base_e2e = baseline["gpu"]["e2e_ms"] if baseline else 4120.0
    base_comp = baseline["gpu"]["compute_ms"] if baseline else 4120.0
    base_disp = baseline["gpu"]["e2e_minus_gpu_ms"] if baseline else 0.170
    if base_disp <= 0:
        base_disp = 0.170

    names = [d["params"]["name"] for d in data]
    colors_list = [scenario_color(d["params"]) for d in data]
    x = np.arange(len(data))
    short_labels = [nice_label(n, d["params"]) for n, d in zip(names, data)]

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

    # ── Plot 2: V3D Clock Stability Across EVERY Scenario ────────────────
    fig, ax = plt.subplots(figsize=(14, 5.5))
    mean_clocks = []
    min_clocks = []
    max_clocks = []

    for d in data:
        dvfs = d["dvfs"]
        active = get_gpu_active_dvfs(dvfs)
        if active.empty:
            v3d_vals = dvfs[dvfs["v3d_hz"] > 0]["v3d_hz"].values / 1e6 if not dvfs.empty else [960.0]
        else:
            v3d_vals = active["v3d_hz"].values / 1e6
        if len(v3d_vals) == 0:
            v3d_vals = [960.0]

        mean_clocks.append(float(np.mean(v3d_vals)))
        min_clocks.append(float(np.min(v3d_vals)))
        max_clocks.append(float(np.max(v3d_vals)))

    yerr_lower = np.maximum(np.array(mean_clocks) - np.array(min_clocks), 0)
    yerr_upper = np.maximum(np.array(max_clocks) - np.array(mean_clocks), 0)
    b_clk = ax.bar(x, mean_clocks, width=0.5, color=colors_list, edgecolor="black", linewidth=0.6,
                   yerr=[yerr_lower, yerr_upper], capsize=4, error_kw=dict(lw=1.2, capthick=1.2, color="black"))

    for bar, m_clk in zip(b_clk, mean_clocks):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                f"{m_clk:.0f} MHz", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=7.5, rotation=25, ha="right")
    ax.set_ylabel("V3D Clock Frequency (MHz)")
    ax.set_ylim(0, 1150)
    ax.set_title("V3D GPU Clock Frequency (Mean with Min-Max Range Error Bars) Across All Scenarios", fontsize=11)
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_v3d_clock_dist.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_v3d_clock_dist.png")
    plt.close(fig)

    # ── Plot 3: Temperature vs Compute Latency and E2E-GPU Residual ──────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 6.5))

    avg_temps = []
    max_temps = []
    comp_lats = [d["gpu"]["compute_ms"] for d in data]
    disp_lats = [d["gpu"]["e2e_minus_gpu_ms"] for d in data]

    for d in data:
        dvfs = d["dvfs"]
        active = get_gpu_active_dvfs(dvfs)
        if active.empty and not dvfs.empty:
            active = dvfs[dvfs["v3d_hz"] > 0]
        if not active.empty:
            avg_temps.append(float(active["temp_c"].mean()))
            max_temps.append(float(active["temp_c"].max()))
        elif not dvfs.empty:
            avg_temps.append(float(dvfs["temp_c"].mean()))
            max_temps.append(float(dvfs["temp_c"].max()))
        else:
            avg_temps.append(float(d["meta"].get("temp_before_c", 50.0)))
            max_temps.append(float(d["meta"].get("temp_after_c", 50.0)))

    temp_err_upper = np.maximum(np.array(max_temps) - np.array(avg_temps), 0)

    # Left: Dual-Axis Temperature vs Compute Latency across all scenarios
    ax1_twin = ax1.twinx()
    b_t1 = ax1.bar(x, avg_temps, width=0.5, color=colors_list, edgecolor="black", linewidth=0.6,
                   yerr=[np.zeros(len(avg_temps)), temp_err_upper], capsize=3,
                   error_kw=dict(lw=1.0, color="black"), label="Avg Temp (°C, cap=max)")
    l_c1 = ax1_twin.plot(x, comp_lats, "ro-", markersize=6.5, linewidth=1.8, label="Compute Latency (ms)")

    for bar, t_avg in zip(b_t1, avg_temps):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                 f"{t_avg:.1f}°", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    for i, c_lat in enumerate(comp_lats):
        ax1_twin.text(i, c_lat + 400, f"{c_lat:.0f}", ha="center", va="bottom",
                      fontsize=7, fontweight="bold", color="red")

    ax1.set_xlabel("Interference Scenario (All Parameters)")
    ax1.set_ylabel("SoC Temperature (°C)", color="black")
    ax1_twin.set_ylabel("Compute Latency (ms)", color="red")
    ax1.set_title("Temperature vs GPU Compute Latency Across All Scenarios", fontsize=11)
    ax1.set_xticks(x)
    ax1.set_xticklabels(short_labels, fontsize=7.5, rotation=25, ha="right")
    ax1.set_ylim(0, 95)
    lines_1 = [b_t1, l_c1[0]]
    ax1.legend(lines_1, [l.get_label() for l in lines_1], loc="upper left", fontsize=8)

    # Right: Dual-Axis Temperature vs E2E-GPU Residual across all scenarios
    ax2_twin = ax2.twinx()
    b_t2 = ax2.bar(x, avg_temps, width=0.5, color=colors_list, edgecolor="black", linewidth=0.6,
                   yerr=[np.zeros(len(avg_temps)), temp_err_upper], capsize=3,
                   error_kw=dict(lw=1.0, color="black"), label="Avg Temp (°C, cap=max)")
    l_d2 = ax2_twin.plot(x, disp_lats, "s--", color="#D84315", markersize=6.5, linewidth=1.8,
                         label="E2E-GPU Residual (ms)")

    for bar, t_avg in zip(b_t2, avg_temps):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                 f"{t_avg:.1f}°", ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    for i, d_lat in enumerate(disp_lats):
        ax2_twin.text(i, d_lat + 0.08, f"{d_lat:.2f}", ha="center", va="bottom",
                      fontsize=7, fontweight="bold", color="#D84315")

    ax2.set_xlabel("Interference Scenario (All Parameters)")
    ax2.set_ylabel("SoC Temperature (°C)", color="black")
    ax2_twin.set_ylabel("E2E-GPU Residual (ms) = E2E - GPU timer", color="#D84315")
    ax2.set_title("Temperature vs E2E-GPU Residual Across All Scenarios", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(short_labels, fontsize=7.5, rotation=25, ha="right")
    ax2.set_ylim(0, 95)
    lines_2 = [b_t2, l_d2[0]]
    ax2.legend(lines_2, [l.get_label() for l in lines_2], loc="upper left", fontsize=8)

    fig.suptitle("SoC Thermal State vs Compute and E2E-GPU Residuals Across All Parameters", fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "dvfs_gpu_temp_vs_latency.png"), dpi=150)
    print(f"  → {PLOT_DIR}/dvfs_gpu_temp_vs_latency.png")
    plt.close(fig)

    # ── Plot 4: 5-Panel Comparative DVFS Summary Bar Chart ───────────────
    fig, axes = plt.subplots(1, 5, figsize=(20, 5.2))

    # 4a: Avg CPU Freq
    avg_cpu = []
    for d in data:
        active = get_gpu_active_dvfs(d["dvfs"])
        if not active.empty:
            avg_cpu.append(active["cpu_khz"].mean() / 1000)
        elif not d["dvfs"].empty:
            avg_cpu.append(d["dvfs"]["cpu_khz"].mean() / 1000)
        else:
            avg_cpu.append(2400.0)

    axes[0].bar(x, avg_cpu, color=colors_list, edgecolor="black", linewidth=0.5)
    axes[0].set_title("Avg CPU Freq\n(GPU active)", fontsize=10)
    axes[0].set_ylabel("MHz")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(short_labels, fontsize=7, rotation=25, ha="right")

    # 4b: Avg V3D Freq
    avg_v3d = []
    for d in data:
        active = get_gpu_active_dvfs(d["dvfs"])
        if not active.empty:
            avg_v3d.append(active["v3d_hz"].mean() / 1e6)
        else:
            v3d_active = d["dvfs"][d["dvfs"]["v3d_hz"] > 0] if not d["dvfs"].empty else pd.DataFrame()
            avg_v3d.append(v3d_active["v3d_hz"].mean() / 1e6 if not v3d_active.empty else 960.0)

    axes[1].bar(x, avg_v3d, color=colors_list, edgecolor="black", linewidth=0.5)
    axes[1].set_title("Avg V3D Clock\n(GPU active)", fontsize=10)
    axes[1].set_ylabel("MHz")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(short_labels, fontsize=7, rotation=25, ha="right")

    # 4c: Max Temperature
    axes[2].bar(x, max_temps, color=colors_list, edgecolor="black", linewidth=0.5)
    axes[2].set_title("Max Temperature\n(run peak)", fontsize=10)
    axes[2].set_ylabel("°C")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(short_labels, fontsize=7, rotation=25, ha="right")
    for i, t in enumerate(max_temps):
        axes[2].text(i, t + 0.3, f"{t:.1f}°", ha="center", fontsize=7.5)

    # 4d: GPU Compute Latency
    axes[3].bar(x, comp_lats, color=colors_list, edgecolor="black", linewidth=0.5)
    axes[3].set_title("GPU Compute Latency\n(kernel execution)", fontsize=10)
    axes[3].set_ylabel("ms")
    axes[3].set_xticks(x)
    axes[3].set_xticklabels(short_labels, fontsize=7, rotation=25, ha="right")
    for i, v in enumerate(comp_lats):
        axes[3].text(i, v + 200, f"{v:.0f}", ha="center", fontsize=7)

    # 4e: E2E-GPU Residual = E2E - GPU timer
    axes[4].bar(x, disp_lats, color=colors_list, edgecolor="black", linewidth=0.5)
    axes[4].set_title("E2E-GPU Residual\n(E2E - GPU timer)", fontsize=10)
    axes[4].set_ylabel("ms")
    axes[4].set_xticks(x)
    axes[4].set_xticklabels(short_labels, fontsize=7, rotation=25, ha="right")
    for i, v in enumerate(disp_lats):
        axes[4].text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=7.5, fontweight="bold")

    fig.suptitle("DVFS State vs GPU Compute Latency vs E2E-GPU Residual Across ALL Parameters",
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
    for d, cpu, v3d, temp in zip(data, avg_cpu, avg_v3d, max_temps):
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