# CPU Contention Subsystem

## Hardware Engine
- **Processor:** 4 × ARM Cortex-A76 cores running up to 2.4 GHz.
- **Cache Hierarchy:** 64 KB L1i/d per core, 512 KB L2 per core, 2 MB shared L3 cache.
- **Interconnect:** ARM DynamIQ Shared Unit (DSU) with hardware cache coherency.

## Benchmark / Stress Tool
- **`cpu_stress.sh`**: Dispatches multi-threaded compute (`sysbench cpu`) or shared L3/DSU cache thrashing (`stress-ng --cache`).
- **Contention Mechanism:** Heavy instruction execution and L3 cache line invalidations, saturating CPU interconnect bandwidth and generating cache line evictions.

## Usage
```bash
./cpu_stress.sh [duration_sec] [compute|cache] [threads]
```
