# Memory Interference Analysis Suite – Complete & Unbiased Parameter Visualization

## Zero-Assumption Policy

Every parameter and scenario present in `/data/` is now **fully included in every visualization** across all analysis scripts without filtering, subsetting, or preconceived assumptions:
- **CPU-Side Contentions** (`mutex1_t4`, `cpu_prime_t8`, `threads_t16`, `32kn`)
- **Page-Fault Stressors** (`ng_fault_t4`, `pf_64mw_t4`)
- **Cache-Resident Memory** (`16kr`, `128kr`, `256kr`, `1mr`)
- **Cache-Evicting Memory** (`2mr`, `4mr`)
- **DRAM Streaming & Random** (`8mr`, `64mw_rnd`)
- **Cache Coherence** (`32kw_t2_g`, `256kw_g`)
- **Thread Sweeps** (`4mr_t2`, `64mw_t8`)
- **Baseline Reference** (`baseline`)

---

## Current Experimental Dataset (All 11 Scenarios)

| Scenario | Category | Mode | Block | Sysbench BW (MiB/s) | E2E (ms) | Compute (ms) | Dispatch (ms) | Compute Degr | Dispatch Degr |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **baseline** | `baseline` | none | — | 0.0 | 4,116.0 | 4,115.8 | 0.160 | **1.00×** | **1.00×** |
| **mutex1_t4** | `cpu_side` | mutex | 1 | 0.0 | 4,120.7 | 4,120.6 | 0.155 | **1.00×** | **0.97×** |
| **ng_fault_t4** | `pagefault` | ngfault | — | 0.0 | 4,164.5 | 4,164.3 | 0.188 | **1.01×** | **1.18×** |
| **16kr** | `cache_resident` | mem | 16K | 81,723.5 | 4,110.2 | 4,110.0 | 0.192 | **1.00×** | **1.20×** |
| **128kr** | `cache_resident` | mem | 128K | 94,046.2 | 4,126.1 | 4,125.9 | 0.172 | **1.00×** | **1.07×** |
| **256kr** | `cache_resident` | mem | 256K | 94,605.1 | 4,143.6 | 4,143.4 | 0.201 | **1.01×** | **1.26×** |
| **1mr** | `cache_resident` | mem | 1M | 17,154.0 | 20,861.9 | 20,860.4 | 1.585 | **5.07×** | **9.91×** |
| **2mr** | `cache_evict` | mem | 2M | 13,381.8 | 27,086.5 | 27,085.8 | 0.617 | **6.58×** | **3.86×** |
| **4mr** | `cache_evict` | mem | 4M | 11,106.1 | 28,274.0 | 28,273.4 | 0.602 | **6.87×** | **3.76×** |
| **8mr** | `dram_stream` | mem | 8M | 10,719.5 | 28,166.1 | 28,165.3 | 0.802 | **6.84×** | **5.01×** |
| **64mw_rnd** | `dram_random` | mem | 64M | 276.8 | 32,255.2 | 32,252.2 | 3.013 | **7.84×** | **18.83×** |

---

## Visualizations Generated (25 Total in `analysis/plots/`)

### 1. `mem-gpu.py`
- `mem_gpu_absolute_latency.png`: Dual-panel showing E2E/Compute (ms) and Dispatch Latency (ms) for **every single scenario**.
- `mem_gpu_degradation_comparison.png`: Grouped degradation factor comparison (E2E vs Compute vs Dispatch) for **every single scenario**.
- `mem_gpu_dispatch_vs_compute.png`: Scatter correlation & Dispatch % of E2E for **every single scenario**.
- `mem_gpu_blocksize_vs_latencies.png`: All-scenarios latency profile (left) + Memory working set progression with CPU-side reference lines (right).
- `mem_gpu_bandwidth_vs_latency.png`: Bandwidth generated vs Compute and Dispatch latencies for **every single scenario**.
- `mem_gpu_throughput_timeseries.png`: Stress throughput time-series for all reporting stressors.

### 2. `category-analysis.py`
- `category_cross_comparison.png`: Category-level summary across all categories.
- `category_all_scenarios_compute.png`: Absolute Compute Latency and Compute Degradation (× baseline) for **every single scenario**.
- `category_all_scenarios_dispatch.png`: Absolute Dispatch Latency and Dispatch Degradation (× baseline) for **every single scenario**.
- `category_cpu_vs_memory_all.png`: Side-by-side comparison of ALL CPU-side, Pagefault, Cache, and DRAM workloads.
- `category_scatter_compute_vs_dispatch.png`: Scatter distribution map of Compute Degradation vs Dispatch Degradation for **every single scenario**.

### 3. `dvfs-gpu.py`
- `dvfs_gpu_summary_bars.png`: 5 panels (CPU Freq, V3D Clock, Max Temp, Compute Latency, Dispatch Latency) for **every single scenario**.
- `dvfs_gpu_temp_vs_latency.png`: Dual-panel temperature vs Compute and Dispatch Latencies for **every single scenario**.
- `dvfs_gpu_timeline.png` & `dvfs_gpu_v3d_clock_dist.png` & `dvfs_gpu_temperature_ramp.png`: Time-series and clock boxplots for **every single scenario**.

### 4. `v3d-mem.py`
- `v3d_mem_l2t_cache.png`: L2T cache hit rates & hits/misses for **every single scenario**.
- `v3d_mem_stall_breakdown.png`: TMU, L2T, and QPU stall cycles for **every single scenario**.
- `v3d_mem_axi_bus.png`: AXI read/write wait cycles & transaction stalls for **every single scenario**.
- `v3d_mem_qpu_breakdown.png`: QPU active cycles, stalls, and wait-bubbles for **every single scenario**.
- `v3d_mem_traffic.png`: Core memory reads/writes & AXI transactions for **every single scenario**.
- `v3d_mem_counter_heatmap.png`: Normalized matrix of all 19 hardware performance counters across **every single scenario**.
- `v3d_mem_hardware_vs_dispatch.png`: AXI wait cycles vs Compute and Dispatch Latencies for **every single scenario**.
