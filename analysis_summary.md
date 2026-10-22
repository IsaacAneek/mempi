# Memory Interference Analysis Suite – Summary

## Created Files

### `/analysis/` directory structure:

| File | Purpose |
|------|---------|
| [`data_loader.py`](file:///home/pi/monpi/mempi/analysis/data_loader.py) | Shared data parsing module – loads `meta.txt`, `gpu_task.txt`, `sysbench.txt`, `dvfs.txt`, `v3d_counters.txt` |
| [`mem-gpu.py`](file:///home/pi/monpi/mempi/analysis/mem-gpu.py) | **Memory stress → GPU latency degradation** (5 plots) |
| [`dvfs-gpu.py`](file:///home/pi/monpi/mempi/analysis/dvfs-gpu.py) | **DVFS parameters → GPU latency degradation** (5 plots) |
| [`v3d-mem.py`](file:///home/pi/monpi/mempi/analysis/v3d-mem.py) | **V3D counters → memory stress correlation** (6 plots) |

---

## Key Findings from Data

### 1. Memory Stress → GPU Latency

| Scenario | Block | DRAM BW | E2E Latency | Degradation |
|----------|-------|---------|-------------|-------------|
| Baseline | — | 0 | 4605 ms | 1.00× |
| 16K seq read | 16K | 85,786 MiB/s | 4092 ms | **0.89×** (faster!) |
| 16K rnd read | 16K | 7,671 MiB/s | 4089 ms | **0.89×** |
| **4M seq read** | **4M** | **10,221 MiB/s** | **20,224 ms** | **4.39×** 🔴 |

> [!IMPORTANT]
> 16K blocks stay in CPU L1/L2 cache → **zero DRAM contention** → no GPU impact.
> 4M blocks evict all CPU caches → every access goes to DRAM → GPU starved on shared memory bus.

### 2. DVFS → GPU Latency

| Metric | Baseline | 16K stress | 4M stress |
|--------|----------|------------|-----------|
| CPU Freq | 2400 MHz | 2400 MHz | 2400 MHz |
| V3D Clock | ~960 MHz | ~960 MHz | ~960 MHz |
| Max Temp | 69.7°C | 71.9°C | 74.1°C |

> [!NOTE]
> **No DVFS throttling observed** in any scenario. CPU and V3D clocks remain constant.
> The 4.39× degradation is **purely from DRAM bandwidth contention**, not thermal/frequency throttling.

### 3. V3D Counters → Memory Stress

| Counter | 4M/Baseline Ratio | Significance |
|---------|-------------------|--------------|
| L2T Memory Stalls | **68.27×** | GPU cache misses delayed by DRAM queue congestion |
| QPU Wait Bubble | **5.60×** | QPU idle, starved for memory data |
| TMU Stalled Cycles | **5.03×** | Texture Memory Unit blocked on L2T→AXI→DRAM path |
| AXI Write Wait | **9.07×** | Bus write contention from CPU stress |
| AXI Read Wait | **2.65×** | Bus read contention |
| L2T Cache Hit Rate | ~94% (stable) | GPU cache itself isn't thrashing |

---

## Plots Generated (16 total)

### `mem-gpu.py` → `analysis/plots/mem_gpu_*.png`
1. **Absolute latency** bar chart (E2E + GPU compute per scenario)
2. **Degradation factor** (× baseline) with annotation
3. **GPU compute vs CPU dispatch overhead** (stacked bar)
4. **Sysbench BW vs GPU latency** (dual-axis: bandwidth bars + latency line)
5. **Throughput time-series** during GPU execution

### `dvfs-gpu.py` → `analysis/plots/dvfs_gpu_*.png`
1. **DVFS timeline** per scenario (CPU freq, V3D clock, temperature subplots)
2. **V3D clock distribution** boxplot during GPU active window
3. **Temperature vs GPU latency** scatter
4. **DVFS summary bars** (4-panel: CPU freq, V3D clock, max temp, E2E latency)
5. **Temperature ramp** comparison across scenarios

### `v3d-mem.py` → `analysis/plots/v3d_mem_*.png`
1. **L2T cache hit rate** + absolute hit/miss counts
2. **Stall cycles breakdown** (TMU, L2T, QPU by type)
3. **AXI bus wait cycles** + stalled transactions
4. **QPU activity breakdown** (active vs stall vs bubble stacked bar)
5. **Memory traffic** (core + AXI read/write transactions)
6. **Normalized counter heatmap** (all key counters × all scenarios, colored by ratio to baseline)

## Running

```bash
cd /home/pi/monpi/mempi
python3 analysis/mem-gpu.py      # Memory stress vs GPU latency
python3 analysis/dvfs-gpu.py     # DVFS vs GPU latency
python3 analysis/v3d-mem.py      # V3D counters vs memory stress
```

All plots are saved to `analysis/plots/`.
