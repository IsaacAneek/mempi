# DSI Display DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** Dual MIPI DSI display DMA engines on RP1 (`dsi@110000`, `dsi@128000`).
- **Function:** Real-time periodic DMA read engine fetching framebuffer pixel rows across PCIe to drive MIPI DSI panels.
- **Interconnect:** RP1 AXI bus fabric -> PCIe 2.0 x4 link -> BCM2712 system memory controller.

## Benchmark / Stress Tool
- **`dsi_dma_stress.sh` / `dsi_dma_stress.py`**: Executes continuous high-rate framebuffer line fetch loops simulating display rasterization.
- **Contention Mechanism:** Periodic real-time DMA reads with unyielding latency constraints, inducing arbitration stalls on lower-priority bulk transfers.

## Usage
```bash
./dsi_dma_stress.sh [duration_sec] [resolution]
```
