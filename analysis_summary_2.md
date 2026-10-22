# Memory Interference Analysis Suite – Latency & Dispatch Overhead

## Updated `/analysis/` Scripts

All scripts have been updated to explicitly extract, correlate, and visualize **Dispatch Latency** ($L_{\text{dispatch}} = L_{\text{E2E}} - L_{\text{compute}}$) alongside GPU Compute Latency and DVFS/Hardware counter metrics:

| Script | Purpose & Key Visualizations |
|--------|------------------------------|
| [`data_loader.py`](file:///home/pi/monpi/mempi/analysis/data_loader.py) | Parses data files, computes `compute_ms`, `dispatch_latency_ms`, `dispatch_latency_us` per dispatch, and `dispatch_ratio_pct`. Dynamic scenario category classification (cache-resident, L2/L3-resident, cache-evict). |
| [`mem-gpu.py`](file:///home/pi/monpi/mempi/analysis/mem-gpu.py) | **Memory Stress vs Latency (E2E, Compute, Dispatch)**:<br>• `mem_gpu_absolute_latency.png`: Dual-panel E2E/Compute (seconds) vs Dispatch (fractions of ms)<br>• `mem_gpu_degradation_comparison.png`: Grouped degradation factor (× baseline) for E2E, Compute, and Dispatch<br>• `mem_gpu_dispatch_vs_compute.png`: Dispatch vs Compute scatter & Dispatch % of E2E<br>• `mem_gpu_blocksize_vs_latencies.png`: Latency progression across L1, L2/L3, and DRAM<br>• `mem_gpu_bandwidth_vs_latency.png`: Memory bandwidth consumed vs Compute & Dispatch latencies |
| [`dvfs-gpu.py`](file:///home/pi/monpi/mempi/analysis/dvfs-gpu.py) | **DVFS Parameters vs Compute & Dispatch Latency**:<br>• `dvfs_gpu_summary_bars.png`: 5-panel comparison (CPU Freq, V3D Clock, Max Temp, Compute Latency, Dispatch Latency)<br>• `dvfs_gpu_temp_vs_latency.png`: Temperature vs Compute Latency and Temperature vs Dispatch Latency<br>• `dvfs_gpu_timeline.png` & `dvfs_gpu_temperature_ramp.png` |
| [`v3d-mem.py`](file:///home/pi/monpi/mempi/analysis/v3d-mem.py) | **V3D Hardware Counters vs Latencies**:<br>• `v3d_mem_hardware_vs_dispatch.png`: AXI read wait cycles vs Compute and Dispatch Latencies<br>• `v3d_mem_l2t_cache.png`, `v3d_mem_stall_breakdown.png`, `v3d_mem_axi_bus.png`, `v3d_mem_qpu_breakdown.png`, `v3d_mem_counter_heatmap.png` |

---

## Experimental Findings Across the Cache Hierarchy

### Complete Metric Breakdown

| Scenario | Block Size | Category | Sysbench BW (MiB/s) | E2E (ms) | Compute (ms) | Dispatch (ms) | Disp/Iter ($\mu$s) | Compute Degr | Dispatch Degr | Disp % |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **baseline** | — | Baseline | 0.0 | 4,124.0 | 4,123.8 | 0.176 | 0.440 | **1.00×** | **1.00×** | 0.004% |
| **16kr** | 16 KiB | Cache-Resident (L1) | 81,371.7 | 4,110.5 | 4,110.2 | 0.230 | 0.575 | **1.00×** | **1.31×** | 0.006% |
| **128kr** | 128 KiB | Cache-Resident (L1) | 94,334.6 | 4,128.4 | 4,128.3 | 0.182 | 0.455 | **1.00×** | **1.03×** | 0.004% |
| **256kr** | 256 KiB | Cache-Resident (L1 boundary) | 94,620.6 | 4,139.5 | 4,136.5 | 2.912 | 7.280 | **1.00×** | **16.55×** ⚡ | 0.070% |
| **1mr** | 1 MiB | L2/L3-Resident | 17,127.6 | 20,837.8 | 20,837.4 | 0.403 | 1.008 | **5.05×** 🔴 | **2.29×** | 0.002% |
| **2mr** | 2 MiB | L2/L3 boundary | 13,428.6 | 26,956.6 | 26,953.0 | 3.594 | 8.985 | **6.54×** 🔴 | **20.42×** ⚡ | 0.013% |
| **4mr** | 4 MiB | Cache-Evict (DRAM) | 11,021.9 | 28,023.3 | 28,021.9 | 1.436 | 3.590 | **6.80×** 🔴 | **8.16×** | 0.005% |
| **8mr** | 8 MiB | Cache-Evict (DRAM) | 10,705.2 | 28,075.2 | 28,074.6 | 0.666 | 1.665 | **6.81×** 🔴 | **3.78×** | 0.002% |

---

## Key Technical Takeaways

> [!IMPORTANT]
> **1. The Compute Latency Cliff (DRAM Contention):**
> * For blocks $\le 256\text{ KiB}$ (`16kr`, `128kr`, `256kr`), sysbench fits in CPU L1 cache. The GPU memory bus is uncontested, and Compute Latency remains completely stable at $\sim 4110 - 4136\text{ ms}$ ($1.00\times$).
> * Once the block size exceeds $256\text{ KiB}$ (`1mr`, `2mr`, `4mr`, `8mr`), CPU memory traffic spills out of L1/L2 and floods the shared DRAM bus. Compute Latency immediately degrades by **$5.05\times$ to $6.81\times$** ($20.8\text{ s} - 28.1\text{ s}$).

> [!WARNING]
> **2. The Dispatch Latency Spikes (CPU Driver Contention):**
> * Dispatch Latency measures the CPU-side overhead of calling `glDispatchCompute()`, issuing `glMemoryBarrier()`, managing command queue buffers, and executing `glFinish()`.
> * Unlike Compute Latency (which plateaus once DRAM is saturated at $4\text{M} - 8\text{M}$), **Dispatch Latency peaks dramatically at cache boundaries:**
>   * At $256\text{ KiB}$ (L1 threshold): **$16.55\times$ degradation** ($2.912\text{ ms}$ vs $0.176\text{ ms}$ baseline).
>   * At $2\text{ MiB}$ (L2/L3 threshold): **$20.42\times$ degradation** ($3.594\text{ ms}$ vs $0.176\text{ ms}$ baseline).
> * This occurs because CPU driver code and DMA command ringbuffers compete for CPU cache lines and interconnect buffers during cache eviction.

> [!NOTE]
> **3. DVFS Stability:**
> * CPU frequency stays at $2400\text{ MHz}$ and V3D clock remains at $960\text{ MHz}$ in all scenarios.
> * Maximum temperature remains below $78^\circ\text{C}$ (no thermal throttling flags triggered).
> * Therefore, **all latency degradation is hardware memory bus and cache contention, not clock throttling**.

---

## How to Re-Run

```bash
cd /home/pi/monpi/mempi
python3 analysis/mem-gpu.py
python3 analysis/dvfs-gpu.py
python3 analysis/v3d-mem.py
```
All plots are refreshed in [`/home/pi/monpi/mempi/analysis/plots/`](file:///home/pi/monpi/mempi/analysis/plots/).
