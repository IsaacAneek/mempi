# Transposer / 2D Matrix Contention Subsystem

## Hardware Engine
- **Hardware Block:** BCM2712 Transposer Engine.
- **Function:** Real-time 2D data transposition, matrix rotation, and strided memory transformations.
- **Interconnect:** Master AXI bus client on the BCM2712 system memory crossbar.

## Benchmark / Stress Tool
- **`transposer_stress.sh` / `transposer_workload.py`**: Executes continuous 64 MiB 2D matrix transpositions (`src.T -> dst`).
- **Contention Mechanism:** Heavy stride-by-stride memory reads and writes that defeat DRAM row-buffer locality, creating massive DRAM bank precharge/activation conflicts and memory channel stalls.

## Usage
```bash
./transposer_stress.sh [duration_sec] [matrix_dim]
```
