# System & Hardware Limitations

During the development of this CPU-GPU memory interference benchmarking suite for the Raspberry Pi 5, we encountered several architectural, software, and hardware limitations. This document records each limitation and exactly how we mitigated it to achieve a working benchmark.

---

### 1. Lack of Fine-Grained GPU Profiling Tools
*   **The Limitation**: The research paper relied heavily on NVIDIA tools (`ncu` / `nvprof`) to extract over 140,000 micro-architectural hardware counters (L2 cache misses, warp divergence, LDST stalls) to train machine learning models. The Raspberry Pi 5's VideoCore VII (using the open-source V3DV Mesa driver) does not expose these low-level hardware performance counters to standard user-space.
*   **The Mitigation**: We pivoted the benchmark from micro-metric ML prediction to **macroscopic latency degradation**. Instead of counting cache misses, we wrote a script (`profiler.sh`) to log high-level system attributes (`top`, `free`, `vcgencmd`) and directly measured the `Total GPU execution time` to objectively prove that memory interference was happening.

### 2. Headless GPU Execution over SSH
*   **The Limitation**: Standard GPU workloads (like `vkcube` or standard OpenGL ES applications) require an active X11 or Wayland window surface to render to. When benchmarking over headless SSH, these programs instantly crash due to the missing `$DISPLAY` environment variable.
*   **The Mitigation**: We entirely bypassed the windowing system by writing a custom **OpenGL ES 3.1 Compute Shader** (`gpu_task.c`) that utilizes a `Surfaceless` EGL context. By explicitly requesting `EGL_PBUFFER_BIT` (Pixel Buffer), we forced EGL to grant us an off-screen, headless-compatible GPU connection.

### 3. Driver "Dead Code" Optimization (0.000s Execution)
*   **The Limitation**: Modern Mesa drivers utilize incredibly aggressive LLVM Dead Code Elimination. If a compute shader calculates millions of data points on the GPU but the C program never reads those results back to the CPU, the driver silently deletes the entire dispatch queue to save power. This caused our benchmark to constantly report `0.000s` execution times.
*   **The Mitigation**: We explicitly mapped the output SSBO (Shader Storage Buffer Object) back into the CPU's memory space using `glMapBufferRange` and printed a single byte from it. This created a strict CPU-GPU dependency, completely defeating the optimizer and forcing the GPU to physically execute all 400 memory-intensive iterations.

### 4. GPU Workgroup Hardware Limits
*   **The Limitation**: The OpenGL ES 3.1 specification dictates a minimum hardware limit of `65,535` for `GL_MAX_COMPUTE_WORK_GROUP_COUNT` in the X dimension. When trying to process an array of 16 million elements at 1 element-per-thread (workgroup size 256), we requested `65,536` workgroups. The driver instantly aborted the math with a silent `GL_INVALID_VALUE` error.
*   **The Mitigation**: We modified the GLSL shader architecture to process **4 array elements per thread**. This divided our required dispatch workgroups by 4 (down to 16,384), comfortably fitting inside the Raspberry Pi 5's hardware limits.

### 5. Contiguous Memory Allocator (CMA) Fragmentation
*   **The Limitation**: Attempting to allocate massive 64 MB contiguous blocks of RAM on the GPU failed silently because it exceeded the Pi 5's CMA fragmentation limits. `glBufferData` returned a 0-byte buffer, causing `glMapBufferRange` to return `NULL` and the shader to finish instantly.
*   **The Mitigation**: We reduced the array sizes to 8 million floats (32 MB per buffer). This size is still massively larger than the Pi 5's combined L2/L3 caches (guaranteeing raw DRAM access to cause interference), but small enough to safely fit inside the contiguous memory allocator. We also added explicit `glGetError()` checks to catch any future memory allocation failures.

### 6. DVFS Masking (Dynamic Voltage and Frequency Scaling)
*   **The Limitation**: When running the isolated GPU task, the CPU was idle, causing the power management firmware to keep the RAM and internal bus clocks in a low-power state. When the CPU memory interferer was introduced, the SoC hit 100% CPU load. The firmware reacted by "boosting" all memory and bus clocks to their absolute maximum. This massive clock boost so dramatically accelerated the GPU that it completely masked the memory interference, causing the GPU to run *faster* under heavy interference.
*   **The Mitigation**: Linux CPU `scaling_governor` overrides were ignored by the Broadcom firmware. To solve this, we created `cpu_spinner.c`—a C program that runs an infinite math loop in CPU registers. By running 3 `cpu_spinner` instances during the "Isolated" run, we trick the firmware into detecting 100% CPU load and boosting the system clocks, but without generating a single byte of DRAM traffic. This perfectly isolates the clock-boosting effect from the physical memory interference.

### 7. Bandwidth Saturation Thresholds
*   **The Limitation**: A single `meminterf` process doing `memset` operations is completely incapable of saturating the massive ~17 GB/s bandwidth of the Pi 5's LPDDR4X memory.
*   **The Mitigation**: We parallelized the CPU stress test inside `run_cpu_gpu_interference.sh` by spawning **3 concurrent instances** of `meminterf` and pushing them to the background. This fully exhausts the 4-core CPU, completely saturating the memory controller's bandwidth and properly starving the GPU.

