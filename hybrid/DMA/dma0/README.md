# BCM2712 DMA0 Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 DMA0 controller (`dma@10000`, 5 physical channels `dma0chan0`..`dma0chan4`).
- **Function:** General-purpose 32/40-bit Direct Memory Access engine for peripheral and memory-to-memory operations.
- **Interconnect:** Master AXI bus client on the BCM2712 internal crossbar.

## Benchmark / Stress Tool
- **`dma0_stress.sh` / `dma0_stress.py`**: Dispatches simultaneous memory-to-memory block transfers across all 5 channels.
- **Contention Mechanism:** Heavy continuous block copy requests saturating system bus bandwidth and arbitrating against CPU/GPU traffic.

## Usage
```bash
./dma0_stress.sh [duration_sec] [block_kb]
```
