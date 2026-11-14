# PCIe 2.0 x4 Interconnect Contention Subsystem

## Hardware Engine
- **Hardware Block:** Broadcom BCM2712 PCIe Host Bridge to Raspberry Pi RP1 Southbridge Endpoint (`0002:00:00.0` -> `0002:01:00.0`).
- **Specification:** PCIe 2.0 × 4 lanes (500 MB/s per lane, up to 2.0 GB/s aggregate throughput).
- **Function:** Carries all external I/O, Ethernet packets, USB data, CSI camera streams, and DSI display data between RP1 and BCM2712.

## Benchmark / Stress Tool
- **`pcie_stress.sh` / `pcie_workload.py`**: Executes rapid bidirectional PCIe transactions and configuration register scans.
- **Contention Mechanism:** Link-level packet contention and PCIe transaction layer packet (TLP) arbitration delays between real-time (CSI/DSI) and bulk (USB/Ethernet) traffic.

## Usage
```bash
./pcie_stress.sh [duration_sec]
```
