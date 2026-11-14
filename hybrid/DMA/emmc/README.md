# SD / eMMC Descriptor DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** Broadcom SD/eMMC host controller descriptor DMA engine (ADMA2).
- **Function:** Asynchronous scatter-gather descriptor table processing and block memory transfers.
- **Interconnect:** Master DMA client on the BCM2712 system memory bus.

## Benchmark / Stress Tool
- **`emmc_dma_stress.sh` / `emmc_dma_stress.py`**: Executes chained scatter-gather descriptor DMA list sweeps.
- **Contention Mechanism:** Large block scatter-gather memory writes with memory-mapped descriptor accesses competing against CPU/GPU data streams.

## Usage
```bash
./emmc_dma_stress.sh [duration_sec] [descriptors]
```
