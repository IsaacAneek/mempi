# Camera (CSI-2 / UNICAM) Contention Subsystem

## Hardware Engine
- **Hardware Block:** Dual MIPI CSI-2 receivers on RP1 (`csi@110000`, `csi@128000`) and UNICAM DMA.
- **Function:** Real-time serial-to-parallel sensor packet deserialization and DMA packet routing across PCIe.
- **Interconnect:** RP1 AXI bus fabric -> PCIe 2.0 x4 link -> BCM2712 system memory.

## Benchmark / Stress Tool
- **`camera_stress.sh` / `camera_workload.py`**: High-rate continuous circular ring-buffer capture pump mimicking 60+ FPS multi-camera ingestion.
- **Contention Mechanism:** Sustained PCIe inbound writes and high-priority QoS traffic at the RP1 AXI arbiter competing with USB and Ethernet.

## Usage
```bash
./camera_stress.sh [duration_sec]
```
