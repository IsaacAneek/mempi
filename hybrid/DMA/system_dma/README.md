# BCM2712 System DMA Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 System DMA controller and kernel DMA-buf heap (`/dev/dma_heap/system`).
- **Function:** Manages physically contiguous / scatter-gather DMA buffers and system-wide cache coherency invalidation.
- **Interconnect:** System memory bus master carrying uncached and coherent DMA transactions.

## Benchmark / Stress Tool
- **`system_dma_stress.sh` / `system_dma_stress.py`**: Allocates large DMA-bufs via the Linux dma-buf heap framework and drives continuous `DMA_BUF_IOCTL_SYNC` hardware cache clean/invalidate cycles.
- **Contention Mechanism:** Heavy cache line writebacks and CPU-to-DMA invalidations generating memory channel write traffic.

## Usage
```bash
./system_dma_stress.sh [duration_sec] [size_mb]
```
