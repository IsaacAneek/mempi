# JPEG Acceleration Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 Media / JPEG Engine.
- **Function:** Hardware JPEG decoding and accelerated Discrete Cosine Transform (DCT) matrix processing.
- **Interconnect:** AXI bus client on the BCM2712 memory subsystem.

## Benchmark / Stress Tool
- **`jpeg_stress.sh` / `jpeg_workload.py`**: Executes continuous JPEG decoding and uncompressed pixel rasterization into system memory.
- **Contention Mechanism:** Bursts of variable-length decoding writes into memory buffers, testing memory controller responsiveness under streaming media decompression.

## Usage
```bash
./jpeg_stress.sh [duration_sec]
```
