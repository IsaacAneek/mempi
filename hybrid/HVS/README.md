# HVS (Hardware Video Scaler) Contention Subsystem

## Hardware Engine
- **Hardware Block:** Broadcom VideoCore VI / BCM2712 Hardware Video Scaler (HVS) & VC4 DRM (`/dev/dri/card1`).
- **Function:** Real-time multi-plane composition, scaling, format conversion, and display scanout to HDMI / DSI.
- **Interconnect:** High-priority real-time DMA master on the BCM2712 system memory bus.

## Benchmark / Stress Tool
- **`hvs_stress.sh` / `hvs_workload.py`**: Interacts with the VC4 DRM KMS driver to allocate multi-plane dumb framebuffers and execute continuous multi-layer compositing passes.
- **Contention Mechanism:** Heavy continuous display read traffic over the memory interconnect. Due to display real-time QoS deadlines, HVS reads can preempt or stall non-real-time GPU/CPU memory transactions.

## Usage
```bash
./hvs_stress.sh [duration_sec]
```
