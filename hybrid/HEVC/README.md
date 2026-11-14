# HEVC Video Decoder Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 Hardware H.265 / HEVC decoder (`codec@800000`, `/dev/video19`, `rpi-hevc-dec`).
- **Capabilities:** Stateless hardware decoding up to 4Kp60 with direct DMA to memory.
- **Interconnect:** Master AXI bus client on the BCM2712 system interconnect.

## Benchmark / Stress Tool
- **`hevc_stress.sh` / `hevc_workload.py`**: Drives the hardware `/dev/video19` V4L2 multi-planar queueing interface and multi-threaded video stream decoding, generating continuous memory traffic.
- **Contention Mechanism:** Bursts of AXI memory transactions from the video decode pipeline competing with CPU and GPU memory requests.

## Usage
```bash
./hevc_stress.sh [duration_sec] [hardware|software|both]
```
