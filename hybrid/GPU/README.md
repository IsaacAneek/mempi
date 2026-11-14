# GPU Contention Subsystem

## Hardware Engine
- **Processor:** Broadcom VideoCore VII (V3D 7.1.10.2).
- **Compute Architecture:** 12 QPU vector execution units, Texturing Memory Units (TMU), Level-2 Tile (L2T) cache.
- **Interconnect:** Master AXI interface to BCM2712 system memory bus.

## Benchmark / Stress Tool
- **`gpu_stress.sh`**: Dispatches high-intensity OpenGL ES 3.1 compute shaders across 8192 workgroups manipulating 64 MiB Shader Storage Buffer Objects (SSBO).
- **Contention Mechanism:** Heavy parallel AXI read/write bursts to system memory and saturation of the V3D L2T cache and bus queues.

## Usage
```bash
./gpu_stress.sh [duration_sec]
```
