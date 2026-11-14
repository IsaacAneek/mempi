# USB xHCI DMA Machinery Contention Subsystem

## Hardware Engine
- **Hardware Block:** Dual USB 3.0 / USB 2.0 xHCI host controllers on RP1 (`usb@200000`, `usb@300000`) and internal USB DMA transfer machinery.
- **Function:** Asynchronous Transfer Request Block (TRB) processing and scatter-gather payload DMA across PCIe.
- **Interconnect:** RP1 AXI bus fabric -> PCIe 2.0 x4 link -> BCM2712 system memory controller.

## Benchmark / Stress Tool
- **`usb_dma_stress.sh` / `usb_dma_stress.py`**: Executes parallel USB TRB event-ring processing and payload DMA pushes across multiple concurrent USB transfer endpoints.
- **Contention Mechanism:** Bursts of bulk and isochronous DMA packets traversing the PCIe link and competing for memory access slots.

## Usage
```bash
./usb_dma_stress.sh [duration_sec] [streams]
```
