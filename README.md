# Raspberry Pi 5 CPU-GPU Memory Interference Profiler

This project contains a basic profiling and benchmarking suite designed to study memory interference between the CPU and GPU on a Raspberry Pi 5, inspired by the concepts in "Machine Learning Techniques for Understanding and Predicting Memory Interference in CPU-GPU Embedded Systems".

## Project Structure

*   `setup_ssh.sh`: Script to automate passwordless SSH setup to the Raspberry Pi.
*   `deploy.sh`: Script to push the codebase to the remote Raspberry Pi via `rsync`.
*   `src/`: Contains the source code for the memory interferer and profiling scripts.
    *   `meminterf.c`: A C program that continuously performs memory writes to saturate CPU-to-DRAM bandwidth.
    *   `gpu_task.c`: A headless OpenGL ES 3.1 compute shader to generate deliberate GPU memory workload.
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

### 1. SSH Deployment (If running from a host machine)
To automatically push this code to a remote Raspberry Pi, use the provided scripts:
1. Make your SSH passwordless: `./setup_ssh.sh`
2. Sync the code: `./deploy.sh`

### 2. Prerequisites (On the Raspberry Pi)
Ensure you have a C compiler, `make`, `bc`, and the EGL/GLES development headers installed to compile the headless GPU task.
```bash
sudo apt update
sudo apt install build-essential bc libegl1-mesa-dev libgles2-mesa-dev
```

### 3. GPU Workload Tool (Optional/Legacy):
To generate visual GPU traffic, you can install `vulkan-tools` to use `vkcube` as a visual workload (the suite now defaults to the headless `gpu_task`).
```bash
sudo apt install vulkan-tools
```

### 4. Build the Project:
```bash
make
```
This will compile the `meminterf` C program and the `gpu_task` and place them in the `build/` directory. The `meminterf` program performs continuous `memset` operations on a 50MB buffer to saturate the CPU-to-DRAM memory bandwidth, simulating the "CPU-side memory-intensive workloads" described in the paper.

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
To observe deliberate interference and measure the latency degradation of a GPU workload, run the CPU-GPU interference test. This script will run the custom headless OpenGL ES compute shader (`gpu_task`) first in isolation, and then again while the CPU memory interferer is spamming the DRAM.
```bash
cd test
./run_cpu_gpu_interference.sh
```
*Note: Because `gpu_task.c` uses a Surfaceless EGL context, it runs entirely headlessly. You do not need an X11/Wayland display connected, and it works perfectly over standard SSH.*

