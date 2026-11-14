# BCM2712 DMA1 Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 DMA1 controller (`dma@10600`, 5 physical channels `dma1chan0`..`dma1chan4`).
- **Function:** Dedicated high-burst Direct Memory Access controller.
- **Interconnect:** Master AXI bus client on the BCM2712 system interconnect.

## Benchmark / Stress Tool
- **`dma1_stress.sh` / `dma1_stress.py`**: Executes parallel large burst transfers across all 5 DMA1 channels.
- **Contention Mechanism:** Large AXI burst transfers occupying memory arbitration slots and displacing cache lines.

## Usage
```bash
./dma1_stress.sh [duration_sec] [burst_kb]
```
