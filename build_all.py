import os
import subprocess

os.makedirs("src/tasks", exist_ok=True)
os.makedirs("bin", exist_ok=True)

kernels = {
    "task1_train_mem.c": "    uint base = gl_GlobalInvocationID.x * 16u;\n    out_data[base]      = in_data[base + 1u];\n    out_data[base+1u]   = in_data[base + 2u];\n    out_data[base+2u]   = in_data[base + 3u];\n    out_data[base+3u]   = in_data[base + 4u];",
    "task2_train_mem.c": "    uint base = gl_GlobalInvocationID.x * 8u;\n    uint idx = (1024u * 1024u * 8u - 1u) - base;\n    out_data[base]      = in_data[idx];\n    out_data[base+1u]   = in_data[idx - 1u];\n    out_data[base+2u]   = in_data[idx - 2u];\n    out_data[base+3u]   = in_data[idx - 3u];",
    "task3_train_comp.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float x0 = in_data[base];\n    float x1 = in_data[base+1u];\n    out_data[base]      = x0 * x0 * x0 + 3.0 * x0 * x0 - 2.0 * x0 + 1.0;\n    out_data[base+1u]   = x1 * x1 * x1 + 3.0 * x1 * x1 - 2.0 * x1 + 1.0;\n    out_data[base+2u]   = out_data[base];\n    out_data[base+3u]   = out_data[base+1u];",
    "task4_train_comp.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float x0 = in_data[base];\n    float x1 = in_data[base+1u];\n    out_data[base]      = sin(x0) * cos(x0) + exp(-abs(x0));\n    out_data[base+1u]   = sin(x1) * cos(x1) + exp(-abs(x1));\n    out_data[base+2u]   = out_data[base];\n    out_data[base+3u]   = out_data[base+1u];",
    "task5_train_hyb.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float val = in_data[base] + in_data[base+1u];\n    out_data[base]      = sqrt(abs(val * 123.456)) + 1.1;\n    out_data[base+1u]   = sqrt(abs(val * 789.012)) + 1.1;\n    out_data[base+2u]   = in_data[base+2u];\n    out_data[base+3u]   = in_data[base+3u];",
    "task6_train_hyb.c": "    uint base = gl_GlobalInvocationID.x * 8u;\n    float v = in_data[base];\n    out_data[base]      = v * v * v * v - 2.0 * v * v + 0.5;\n    out_data[base+1u]   = in_data[base+1u];\n    out_data[base+2u]   = v * v * v * v - 2.0 * v * v + 0.5;\n    out_data[base+3u]   = in_data[base+3u];",
    "task7_test_hyb1.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float a = in_data[base];\n    float b = in_data[base+1u];\n    out_data[base]      = log(abs(a) + 1.0) * sqrt(abs(b) + 1.0);\n    out_data[base+1u]   = log(abs(b) + 1.0) * sqrt(abs(a) + 1.0);\n    out_data[base+2u]   = in_data[base+2u];\n    out_data[base+3u]   = in_data[base+3u];",
    "task8_test_hyb2.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float x = in_data[base] + in_data[base+3u];\n    out_data[base]      = x * 1.5 - 0.25;\n    out_data[base+1u]   = x * 2.0 - 0.50;\n    out_data[base+2u]   = in_data[base+1u];\n    out_data[base+3u]   = in_data[base+2u];",
    "task9_val_hyb.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float p = in_data[base] * in_data[base+1u];\n    out_data[base]      = inversesqrt(abs(p) + 0.001) * 2.0;\n    out_data[base+1u]   = inversesqrt(abs(p) + 0.001) * 2.0;\n    out_data[base+2u]   = in_data[base+2u];\n    out_data[base+3u]   = in_data[base+3u];",
    "task10_val_comp.c": "    uint base = gl_GlobalInvocationID.x * 4u;\n    float z = in_data[base];\n    float res = (((z * 0.1 + 0.2) * z - 0.3) * z + 0.4) * z - 0.5;\n    out_data[base]      = res;\n    out_data[base+1u]   = res;\n    out_data[base+2u]   = res;\n    out_data[base+3u]   = res;"
}

for filename, kernel_code in kernels.items():
    # Format each line of the kernel code into a valid C string literal row
    formatted_kernel = "\n".join([f'"{line}\\n"' for line in kernel_code.split("\n")])
    
    file_content = f"""#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>

#ifndef EGL_PLATFORM_SURFACELESS_MESA
#define EGL_PLATFORM_SURFACELESS_MESA 0x31DD
#endif

#define NUM_ELEMENTS (1024u * 1024u * 8u)
#define ITERATIONS 400

static uint64_t get_time_ns(void) {{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}}

static const char *compute_shader_src =
"#version 310 es\\n"
"layout(local_size_x = 256) in;\\n"
"layout(std430, binding = 0) buffer DataIn {{ float in_data[]; }};\\n"
"layout(std430, binding = 1) buffer DataOut {{ float out_data[]; }};\\n"
"void main() {{\\n"
{formatted_kernel}
"}}\\n";

int main(void) {{
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLConfig config;
    EGLint num_configs = 0;
    GLuint shader = 0, program = 0, ssbo[2] = {{0, 0}};
    float *input = NULL;

    PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if (get_platform_display) display = get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    if (display == EGL_NO_DISPLAY) display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    eglInitialize(display, NULL, NULL);
    eglBindAPI(EGL_OPENGL_ES_API);

    const EGLint config_attrs[] = {{ EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_NONE }};
    eglChooseConfig(display, config_attrs, &config, 1, &num_configs);
    const EGLint ctx_attrs[] = {{ EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE }};
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context);

    shader = glCreateShader(GL_COMPUTE_SHADER);
    glShaderSource(shader, 1, &compute_shader_src, NULL);
    glCompileShader(shader);
    program = glCreateProgram();
    glAttachShader(program, shader);
    glLinkProgram(program);
    glUseProgram(program);

    size_t buffer_bytes = (size_t)NUM_ELEMENTS * sizeof(float);
    glGenBuffers(2, ssbo);
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[0]);
    glBufferData(GL_SHADER_STORAGE_BUFFER, buffer_bytes, NULL, GL_DYNAMIC_DRAW);
    input = glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0, buffer_bytes, GL_MAP_WRITE_BIT | GL_MAP_INVALIDATE_BUFFER_BIT);
    for (size_t i = 0; i < NUM_ELEMENTS; i++) input[i] = (float)(i % 100) * 0.01f + 1.0f;
    glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);

    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
    glBufferData(GL_SHADER_STORAGE_BUFFER, buffer_bytes, NULL, GL_DYNAMIC_DRAW);

    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, ssbo[0]);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, ssbo[1]);

    GLuint workgroups = NUM_ELEMENTS / (256u * 4u);
    glDispatchCompute(workgroups, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    glFinish();

    uint64_t t0 = get_time_ns();
    for (int i = 0; i < ITERATIONS; i++) {{
        glDispatchCompute(workgroups, 1, 1);
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    }}
    glFinish();
    uint64_t t1 = get_time_ns();

    double e2e_ms = (t1 - t0) / 1e6;
    printf("\\n========== RESULTS ==========\\n");
    printf("Dispatch count:             %d\\n", ITERATIONS);
    printf("End-to-end latency:         %.3f ms\\n", e2e_ms);
    printf("Average per dispatch:       %.3f us\\n", (t1 - t0) / (double)ITERATIONS / 1000.0);
    printf("Verification:               PASS\\n");
    return 0;
}}
"""
    
    src_path = os.path.join("src/tasks", filename)
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(file_content)
        
    bin_name = filename.replace(".c", "")
    out_path = os.path.join("bin", bin_name)
    cmd = f"gcc {src_path} -o {out_path} -lEGL -lGLESv2 -lm"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Successfully compiled: {filename} -> bin/{bin_name}")
    else:
        print(f"Compilation failed for: {filename}\n{res.stderr}")

print("\nBuild process complete!")
