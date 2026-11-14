# CSI Camera Capture DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** Dual MIPI CSI-2 Capture DMA controllers on RP1 (`csi@110000`, `csi@128000`).
- **Function:** Real-time hardware DMA transferring camera packets from sensor deserializers directly to system RAM.
- **Interconnect:** Master AXI client on RP1 routing over PCIe to BCM2712 memory controller.

## Benchmark / Stress Tool
- **`csi_dma_stress.sh` / `csi_dma_stress.py`**: Simulates 4-lane high-speed MIPI CSI-2 camera packet DMA injection into circular physical page pools.
- **Contention Mechanism:** Constant real-time DMA write streams with strict latency deadlines forcing PCIe QoS prioritization.

## Usage
```bash
./csi_dma_stress.sh [duration_sec] [lanes]
```
