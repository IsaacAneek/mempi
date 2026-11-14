# ISP / PiSP Image Processing Contention Subsystem

## Hardware Engine
- **Hardware Block:** Raspberry Pi Image Signal Processor Backend (`pisp_be@880000`, `/dev/video20`, `pispbe`).
- **Throughput:** Up to 1 gigapixel/second processing throughput.
- **Interconnect:** Master AXI client on BCM2712 crossbar.

## Benchmark / Stress Tool
- **`isp_stress.sh` / `isp_workload.py`**: Interacts with the `pispbe` V4L2 device node and executes multi-plane 4K spatial filtering and tone mapping pipelines.
- **Contention Mechanism:** High-throughput 2D memory pixel ingestion and writeback competing directly with GPU TMU/L2T and CPU L3 requests.

## Usage
```bash
./isp_stress.sh [duration_sec]
```
