# Headless GPU Compute Task (`gpu_task.c`)

This document provides a complete tutorial and explanation of the `gpu_task.c` code. This program is designed to create a heavy, memory-intensive workload on the Raspberry Pi 5's GPU (VideoCore VII) to help us measure latency degradation caused by CPU memory interference.

## The Goal

When benchmarking GPU performance over SSH, the lack of a graphical display (X11/Wayland) often prevents graphical applications from running. To bypass this, we use an **OpenGL ES 3.1 Compute Shader** coupled with a **Surfaceless EGL Context**. This allows us to run pure GPU mathematics and memory operations headlessly.

---

## Pipeline Overview

The pipeline of the `gpu_task.c` program follows these four main steps:
1. **EGL Initialization**: Create a headless connection to the GPU.
2. **Shader Compilation**: Compile the GLSL compute shader that will run on the GPU cores.
3. **Buffer Allocation**: Allocate large chunks of memory (SSBOs) on the GPU.
4. **Execution & Measurement**: Dispatch the shader multiple times and measure how long the GPU takes to complete the work.

---

## Complete Code Breakdown

### 1. Headers and Definitions

```c
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>

#ifndef EGL_PLATFORM_SURFACELESS_MESA
#define EGL_PLATFORM_SURFACELESS_MESA 0x31DD
#endif

#define NUM_ELEMENTS (1024 * 1024 * 8) 
#define ITERATIONS 400
```
*   **Headers**: We include `EGL` (for interfacing with the display system) and `GLES3/gl31.h` (which introduced Compute Shaders to OpenGL ES).
*   **Constants**: We define arrays of 8 million floats. Since each float is 4 bytes, this equals 32 Megabytes per array (64 MB total). This is large enough to completely blow past the L2/L3 caches and force raw DRAM access, which will heavily saturate the GPU-to-DRAM memory bandwidth over 400 iterations.

### 2. The Compute Shader

```c
const char* compute_shader_src =
"#version 310 es\n"
"layout(local_size_x = 256) in;\n"
"layout(std430, binding = 0) buffer DataIn { float in_data[]; };\n"
"layout(std430, binding = 1) buffer DataOut { float out_data[]; };\n"
"void main() {\n"
"    uint base = gl_GlobalInvocationID.x * 4u;\n"
"    out_data[base] = in_data[base] * 1.0001;\n"
"    out_data[base + 1u] = in_data[base + 1u] * 1.0001;\n"
"    out_data[base + 2u] = in_data[base + 2u] * 1.0001;\n"
"    out_data[base + 3u] = in_data[base + 3u] * 1.0001;\n"
"}\n";
```
*   This is written in GLSL (OpenGL Shading Language).
*   Unlike vertex or fragment shaders, a **Compute Shader** is purely for general-purpose calculation (GPGPU).
*   **The Hardware Limit**: In OpenGL ES, the hardware limit for workgroups in the X dimension (`GL_MAX_COMPUTE_WORK_GROUP_COUNT`) is `65,535`. If we processed 1 element per thread over 16 million elements with a workgroup size of 256, we would dispatch `65,536` workgroups, causing the driver to silently fail and finish in 0.000 seconds. By having each thread process **4 elements**, we drop the dispatch size to `16,384`, safely avoiding the crash.
*   This mimics the behavior of the `VADD` (Vector Addition) or `COPY` kernels mentioned in the research paper, which are classified as "Memory Intensive" (M) workloads.

### 3. Step 1: EGL Headless Initialization

```c
const EGLint attribs[] = { 
    EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, 
    EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, 
    EGL_NONE 
};
eglChooseConfig(display, attribs, &config, 1, &num_config);

const EGLint context_attribs[] = { 
    EGL_CONTEXT_CLIENT_VERSION, 3, 
    EGL_NONE 
};
EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attribs);
```
*   Normally, EGL tries to hook into a windowing system. By requesting `EGL_PLATFORM_SURFACELESS_MESA`, we tell the Mesa driver on the Raspberry Pi that we explicitly *do not* want a surface to draw on. This is the magic that allows the script to run flawlessly over an SSH terminal.
*   **The PBuffer Requirement**: Even when running headlessly, if you don't specify an `EGL_SURFACE_TYPE` in the config attributes, EGL defaults to looking for an `EGL_WINDOW_BIT` (a physical screen). We explicitly request `EGL_PBUFFER_BIT` (Pixel Buffer) to guarantee that EGL will successfully find an off-screen, headless-compatible configuration.
*   **The ES 3.1 Context Requirement**: Compute Shaders and SSBOs are strictly **OpenGL ES 3.1** features. Passing `EGL_CONTEXT_CLIENT_VERSION, 3` ensures the Mesa V3DV driver returns the highest supported ES 3.x context (ES 3.1).

### 4. Step 2: Compiling the Shader

```c
GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
glShaderSource(shader, 1, &compute_shader_src, NULL);
glCompileShader(shader);
// ... error checking ...
GLuint program = glCreateProgram();
glAttachShader(program, shader);
glLinkProgram(program);
glUseProgram(program);
```
*   The C program sends the GLSL string to the GPU driver, which compiles it into machine code specific to the VideoCore VII GPU architecture.

### 5. Step 3: Setting up Memory Buffers (SSBOs)

```c
GLuint ssbo[2];
glGenBuffers(2, ssbo);

glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[0]);
glBufferData(GL_SHADER_STORAGE_BUFFER, NUM_ELEMENTS * sizeof(float), NULL, GL_DYNAMIC_DRAW);
glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, ssbo[0]);
```
*   **SSBO (Shader Storage Buffer Object)**: This allows compute shaders to read and write arbitrary amounts of data.
*   We allocate two 64MB buffers on the GPU. One is bound to index `0` (mapped to `DataIn` in the shader), and the other to index `1` (mapped to `DataOut`).

### 6. Step 4: Dispatching and Measuring Time

```c
// Warmup
glDispatchCompute(workgroups, 1, 1);
glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
glFinish();
```
*   **Warmup**: We run the shader once before starting the timer. This ensures the GPU has woken up from its idle power state and the memory pages are fully mapped, preventing a "cold start" from skewing our benchmark.

```c
double start_time = get_time();

for(int i = 0; i < ITERATIONS; i++) {
    glDispatchCompute(workgroups, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
}
glFinish(); // Block until GPU operations complete

double end_time = get_time();
```
*   **glDispatchCompute**: We tell the GPU to execute the shader. 
*   **glMemoryBarrier**: Ensures that all memory writes from the current iteration finish before the next iteration begins.
*   **glFinish**: Forces the CPU to wait until the GPU has completely finished all dispatched commands.

### 7. Step 5: Forcing Execution (Beating the Optimizer)

```c
glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
float* out_ptr = (float*)glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0, sizeof(float), GL_MAP_READ_BIT);
if (out_ptr) {
    printf("[GPU Task] Verification sample: output[0] = %f\n", out_ptr[0]);
    glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
}
```
*   **Dead Code Elimination**: Modern OpenGL drivers (like the V3DV driver) are incredibly smart. If they detect that a program calculates a massive amount of data on the GPU but *never actually reads it back to the CPU or uses it on-screen*, the driver's LLVM compiler will simply delete the entire dispatch queue to save power, resulting in a false `0.000s` execution time.
*   **The Solution**: By explicitly mapping the output buffer to CPU memory space (`glMapBufferRange`) and reading a single byte from it, we create a strict CPU-GPU dependency. This completely defeats the optimizer and forces the GPU to physically execute all 200 memory-intensive iterations.

---

## How this proves Memory Interference

Because this shader is almost entirely constrained by how fast it can move data in and out of the GPU (`out_data[i] = in_data[i]`), it heavily relies on the shared System RAM (LPDDR4) bandwidth.

When the CPU runs `meminterf.c` (which spams `memset`), the CPU and GPU collide at the memory controller. By recording the `Total GPU time` of this script in isolation versus when the CPU is attacking the memory, we gain concrete, measurable proof of the memory latency degradation discussed in the HeSoC-mark paper.

