# Networking (Ethernet / USB / Sockets) Contention Subsystem

## Hardware Engine
- **Hardware Block:** RP1 Gigabit Ethernet GMAC (`ethernet@100000`, `eth0`), integrated Ethernet packet DMA, and PCIe x4 link to BCM2712.
- **Function:** Network frame serialization/deserialization, packet buffering, and ring-buffer DMA.
- **Interconnect:** Traverses the RP1 AXI crossbar, PCIe 2.0 x4 link, and BCM2712 system memory controller.

## Benchmark / Stress Tool
- **`networking_stress.sh` / `networking_workload.py`**: Multi-stream `iperf3` and multi-threaded UDP/TCP high-packet-rate blast.
- **Contention Mechanism:** Rapid allocation and deallocation of Linux `sk_buff` structures, socket DMA page copying, and high-frequency network interrupts causing CPU cache line thrashing.

## Usage
```bash
./networking_stress.sh [duration_sec] [threads]
```
