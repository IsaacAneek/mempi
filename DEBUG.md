# The Debugging Journey: Uncovering Raspberry Pi 5 Secrets

Building a low-level memory benchmark on a modern, dynamically-scaled embedded SoC is incredibly tricky. This document outlines the step-by-step debugging journey we went through to trace down every silent failure, compiler trick, and hardware quirk that tried to break our benchmark.

---

## 1. The "0.000s Execution" Mystery
**The Symptom:**
The C script compiled perfectly, allocated 128 MB of memory on the GPU, and ran 200 iterations of our compute shader... but finished in exactly `0.000` seconds.

**The Debugging Process:**
1. We first suspected `glFinish()` wasn't actually blocking the CPU.
2. We then looked at the math of our `glDispatchCompute` call. We had 16,777,216 array elements and a local workgroup size of 256 threads.
3. `16,777,216 / 256 = 65,536` workgroups.
4. We checked the OpenGL ES 3.1 specification. The minimum guaranteed hardware limit for `GL_MAX_COMPUTE_WORK_GROUP_COUNT` is precisely **65,535**.
5. Because we requested `65,536`, the driver instantly rejected the command with a silent `GL_INVALID_VALUE` error. Since no code executed, it took 0 seconds!

**The Fix:** We rewrote the GLSL shader to process 4 array elements per thread, cutting the dispatch size down to 16,384 workgroups.

---

## 2. The "Dead Code Optimizer" Trap
**The Symptom:**
After fixing the workgroup limit, the code *still* executed in 0.000 seconds. However, this time, inserting a `glGetError()` check revealed `GL_NO_ERROR`. The command was perfectly valid, yet it was skipping execution.

**The Debugging Process:**
1. If the command is perfectly valid but takes no time, the driver is intentionally ignoring it.
2. Modern OpenGL drivers (like the Mesa LLVM compiler) use aggressive **Dead Code Elimination**.
3. We realized that our C program dispatched the GPU to calculate 128 MB of data, but *never actually read the output buffer back to the CPU*.
4. Because the output was never observed, the driver's optimizer concluded the entire dispatch was "dead code" and deleted the queue to save power.

**The Fix:** We added a `glMapBufferRange` block at the end of the script to map the GPU memory into CPU space and print out a single value (`output[0]`). This created a strict CPU dependency, forcing the GPU to physically do the math.

---

## 3. "Failed to map buffer" (The CMA Limit)
**The Symptom:**
When we added `glMapBufferRange`, it returned `NULL` and printed `Warning: Failed to map buffer for verification.`

**The Debugging Process:**
1. Why would mapping return `NULL`? If the mapping is out of bounds.
2. Why would it be out of bounds? If the buffer is actually `0` bytes in size!
3. We investigated `glBufferData`. We were trying to allocate two massive 64 MB contiguous blocks of memory.
4. On the Raspberry Pi, GPU memory is dynamically carved out of system RAM using the **Contiguous Memory Allocator (CMA)**. If the system RAM is even slightly fragmented, a request for a single massive 64 MB contiguous block will silently fail, leaving a 0-byte buffer.

**The Fix:** We shrunk the arrays from 16 Million elements to 8 Million elements (32 MB per buffer). This was small enough to fit inside the CMA fragmentation limits, and the mapping succeeded.

---

## 4. The EGL "Failed to Create Context" Crash
**The Symptom:**
When we explicitly forced the code to request an **OpenGL ES 3.1** context, the entire program crashed at initialization with `Failed to create EGL context`.

**The Debugging Process:**
1. We traced the history of our EGL attributes array.
2. In an attempt to make the script completely headless, we had previously deleted the `EGL_SURFACE_TYPE` flag.
3. If no surface type is specified, `eglChooseConfig` defaults to looking for an `EGL_WINDOW_BIT` (a physical screen).
4. Because we were running headlessly over SSH, no window configs existed. `eglChooseConfig` found 0 matches and returned an uninitialized garbage config to `eglCreateContext`, causing the crash.

**The Fix:** We restored the `EGL_PBUFFER_BIT` (Pixel Buffer) flag. This told EGL that we specifically wanted an off-screen, headless-compatible configuration.

---

## 5. The "Faster Under Interference" Anomaly
**The Symptom:**
Finally, the benchmark ran flawlessly. However, the isolated GPU run took **4.32 seconds**, while the GPU run *under heavy CPU memory interference* took **4.17 seconds**. The GPU was running faster while being attacked!

**The Debugging Process:**
1. Did we saturate the memory bandwidth? A single CPU `memset` consumes ~5 GB/s. The GPU consumes ~6 GB/s. The Pi 5's LPDDR4X bandwidth is ~17 GB/s. We were only using 11 GB/s, meaning no collision occurred.
2. So why did it get faster? **Dynamic Voltage and Frequency Scaling (DVFS)**.
3. During the isolated GPU run, the CPU was idle (0% load), so the Pi 5's firmware kept the memory and internal bus clocks in a low-power, slow state.
4. When we turned on the CPU interferer, the CPU hit 100% load. The firmware panicked and "boosted" the RAM and bus clocks to maximum. The memory sped up so much that it completely overcame the interference penalty, inadvertently accelerating the GPU.
5. Attempting to lock the Linux CPU `scaling_governor` to `performance` failed, as the Broadcom firmware overrides it and scales DRAM independently based on physical CPU load.

**The Fix:** We created a brand new C program, `cpu_spinner.c`, which does pure mathematical additions inside the CPU registers without touching DRAM. During the "Isolated GPU" run, we spawn 3 of these spinners in the background. The firmware sees 100% CPU load and boosts the clocks to maximum, but the DRAM bandwidth remains completely free for the GPU. This "tricks" the Pi 5 into running both benchmarks at peak hardware speeds, finally exposing the true memory interference.

