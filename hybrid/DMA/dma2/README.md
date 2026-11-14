# BCM2712 DMA2 / RP1 PCIe DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 DMA2 controller / RP1 PCIe Bridge Channels (`1000120000.pcie/1f00188000.dma`, 8 physical channels `dma2chan0`..`dma2chan7`).
- **Function:** Transfers data between BCM2712 system memory and RP1 peripherals across the PCIe 2.0 x4 connection.
- **Interconnect:** PCIe endpoint interface to BCM2712 system memory crossbar.

## Benchmark / Stress Tool
- **`dma2_stress.sh` / `dma2_stress.py`**: Executes parallel transfers across all 8 bridge channels.
- **Contention Mechanism:** Saturates PCIe inbound/outbound DMA channels, causing queueing delays in the PCIe transaction layer.

## Usage
```bash
./dma2_stress.sh [duration_sec] [chunk_kb]
```
