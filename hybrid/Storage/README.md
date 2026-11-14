# Storage (SD / eMMC) Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 eMMC2 / SD controller (`mmc@1100000`) and descriptor DMA engine.
- **Function:** Non-volatile storage transfers between eMMC/SD cards and system RAM.
- **Interconnect:** Master DMA client on the BCM2712 system memory bus.

## Benchmark / Stress Tool
- **`storage_stress.sh`**: Uses `fio` with `--direct=1` (bypassing the Linux page cache) and asynchronous random reads and writes (`randrw`).
- **Contention Mechanism:** Descriptor DMA transfers and scatter-gather lists writing directly to physical pages, inducing memory controller latency spikes and bus interrupts.

## Usage
```bash
./storage_stress.sh [duration_sec] [test_size]
```
