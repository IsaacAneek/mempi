# RP1 Synopsys AXI DMAC Contention Subsystem

## Hardware Engine
- **Hardware Block:** Synopsys AXI DMAC on RP1 (`1f00188000.dma`, RP1 Datasheet Chapter 9).
- **Architecture:** 8 independent DMA channels, AXI master bus interface, per-channel FIFO buffers.
- **Function:** High-throughput DMA data transfers between RP1 peripheral interfaces and BCM2712 memory over PCIe.

## Benchmark / Stress Tool
- **`rp1_dmac_stress.sh` / `rp1_dmac_stress.py`**: Executes parallel transfers across all 8 AXI DMAC channels.
- **Contention Mechanism:** Heavy channel arbitration at the RP1 AXI bus and FIFO saturation competing with external I/O streams.

## Usage
```bash
./rp1_dmac_stress.sh [duration_sec] [channels]
```
