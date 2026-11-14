# Ethernet Packet DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** RP1 Gigabit Ethernet MAC (`ethernet@100000`) integrated packet DMA engine.
- **Function:** Autonomous descriptor-driven ring-buffer DMA transferring incoming/outgoing Ethernet frames between system memory and network FIFO.
- **Interconnect:** Master AXI bus client on RP1 traversing the PCIe 2.0 x4 connection.

## Benchmark / Stress Tool
- **`ethernet_dma_stress.sh` / `ethernet_dma_stress.py`**: Executes continuous descriptor ring updates and packet payload DMA transfers.
- **Contention Mechanism:** Bursts of network packet DMA transactions and interrupt generation competing for memory crossbar cycles.

## Usage
```bash
./ethernet_dma_stress.sh [duration_sec] [ring_size]
```
