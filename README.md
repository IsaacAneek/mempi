# Raspberry Pi 5 CPU-GPU Memory Interference Profiler

This project contains a basic profiling and benchmarking suite designed to study memory interference between the CPU and GPU on a Raspberry Pi 5, inspired by the concepts in "Machine Learning Techniques for Understanding and Predicting Memory Interference in CPU-GPU Embedded Systems".

## Project Structure

*   `src/`: Contains the source code for the memory interferer and profiling scripts.
    *   `meminterf.c`: A C program that continuously performs memory writes to saturate CPU-to-DRAM bandwidth.
    *   `profiler.sh`: A shell script to log system metrics (CPU, Memory, Temp, GPU Clock).
*   `build/`: The destination directory for the compiled binaries.
*   `test/`: Scripts to run different benchmarking scenarios.
    *   `run_benchmark.sh`: Runs a baseline memory interference test.
    *   `run_cpu_gpu_interference.sh`: Runs a deliberate CPU-GPU interference test (requires a GPU workload).

## What Can Be Profiled on Raspberry Pi 5

Unlike discrete NVIDIA GPUs (which provide comprehensive profiling tools like `ncu` or `nvprof` as mentioned in the research paper), the VideoCore VII GPU on the Raspberry Pi 5 has a more restricted architecture regarding user-space performance counters.

### What we CAN profile:
*   **System CPU Usage:** Overall and per-core utilization using `top`.
*   **System Memory:** Available and used RAM (shared between CPU and GPU) using `free`.
*   **GPU Clocks & Memory:** Frequencies and memory allocations using Broadcom's `vcgencmd`.
*   **System Temperature:** Thermal status to ensure throttling isn't confounding our results.

### What we CANNOT profile (and why):
*   **Fine-grained GPU Micro-metrics:** Metrics such as L2 cache hit/miss rates, warp divergence, load-store unit (LDST) utilization, and specific stall reasons (which were heavily used in the machine learning models in the PDF).
*   **Why?** The Broadcom VideoCore VII drivers (V3DV Mesa) do not expose these low-level hardware performance counters to standard user-space profiling tools in the same way NVIDIA's CUDA Toolkit does. Capturing them would require specialized Broadcom debugging tools or compiling a custom kernel with specific performance monitoring unit (PMU) access, which is beyond the scope of standard user-space access.

## Setup and Installation

1.  **Prerequisites:**
    Ensure you have a C compiler, `make`, and `bc` installed.
    ```bash
    sudo apt update
    sudo apt install build-essential bc
    ```

2.  **GPU Workload Tool (Required for CPU-GPU interference test):**
    To generate GPU traffic, you can install `vulkan-tools` to use `vkcube` as a visual workload.
    ```bash
    sudo apt install vulkan-tools
    ```

3.  **Build the Interferer:**
    ```bash
    make
    ```
    This will compile the `meminterf` C program and place it in the `build/` directory. The `meminterf` program performs continuous `memset` operations on a 50MB buffer to saturate the CPU-to-DRAM memory bandwidth, simulating the "CPU-side memory-intensive workloads" described in the paper.

## How to Run the System

### 1. Basic Profiling
To just profile the baseline state of the system for 10 seconds:
```bash
./src/profiler.sh 10
```

### 2. CPU Interference Benchmark
To run the profiler while the CPU memory interferer is actively loading the memory bandwidth:
```bash
cd test
./run_benchmark.sh
```

### 3. Deliberate CPU-GPU Interference
To observe deliberate interference, you need to run a GPU workload and the CPU interferer simultaneously.
```bash
cd test
./run_cpu_gpu_interference.sh
```
*Note: The GPU workload script attempts to run `vkcube`. You must have a display connected or run this from a graphical desktop session (Wayland/X11) for the GPU rendering to work properly, as `vulkaninfo` indicated your `DISPLAY` environment variable was not set.*

