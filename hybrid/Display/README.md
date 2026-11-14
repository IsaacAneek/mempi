# Display Interface (DSI / DPI) Contention Subsystem

## Hardware Engine
- **Hardware Block:** Dual MIPI DSI transmitters on RP1 (`dsi@110000`, `dsi@128000`), DPI parallel display, and DSI DMA engines.
- **Function:** Real-time display stream serialization and continuous display refresh DMA reads.
- **Interconnect:** PCIe 2.0 x4 link -> RP1 AXI crossbar -> DSI physical PHY.

## Benchmark / Stress Tool
- **`display_stress.sh` / `display_workload.py`**: High-refresh double-buffered framebuffer scanner exercising real-time memory read cycles.
- **Contention Mechanism:** Constant periodic real-time DMA read demand across the PCIe interconnect with strict deadline requirements.

## Usage
```bash
./display_stress.sh [duration_sec]
```
