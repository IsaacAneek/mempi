#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>

#ifndef EGL_PLATFORM_SURFACELESS_MESA
#define EGL_PLATFORM_SURFACELESS_MESA 0x31DD
#endif

// We use arrays of 8 Million floats. That's 32 MB for input, 32 MB for output.
// Continuously reading and writing 64 MB heavily stresses the GPU memory bandwidth.
// This is perfectly sized to blow past the L2/L3 caches and force DRAM access.
#define NUM_ELEMENTS (1024 * 1024 * 8) 
#define ITERATIONS 400

double get_time() {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec * 1e-6;
}

/*
 * WHY 4 ELEMENTS PER THREAD?
 * 
 * In OpenGL ES 3.1, the guaranteed minimum hardware limit for the number of
 * workgroups in the X dimension (GL_MAX_COMPUTE_WORK_GROUP_COUNT) is 65,535.
 * 
 * Our total array size is 16,777,216 elements. 
 * If we processed 1 element per thread with a local workgroup size of 256, 
 * we would need to dispatch 65,536 workgroups (16777216 / 256 = 65536).
 * Because 65536 > 65535, the driver would instantly abort the dispatch with 
 * a silent GL_INVALID_VALUE error, resulting in a 0.000s execution time.
 * 
 * SOLUTION: By having each thread process 4 elements, we divide the required 
 * workgroups by 4, dropping our dispatch size to 16,384, which easily fits 
 * within the hardware limits of the Raspberry Pi 5's VideoCore VII GPU.
 */
const char* compute_shader_src =
"#version 310 es\n"
"layout(local_size_x = 256) in;\n"
"layout(std430, binding = 0) buffer DataIn { float in_data[]; };\n"
"layout(std430, binding = 1) buffer DataOut { float out_data[]; };\n"
"void main() {\n"
"    uint base = gl_GlobalInvocationID.x * 4u;\n"
"    // Process 4 elements per thread to keep workgroup count below the 65535 hardware limit\n"
"    out_data[base] = in_data[base] * 1.0001;\n"
"    out_data[base + 1u] = in_data[base + 1u] * 1.0001;\n"
"    out_data[base + 2u] = in_data[base + 2u] * 1.0001;\n"
"    out_data[base + 3u] = in_data[base + 3u] * 1.0001;\n"
"}\n";

int main() {
    // 1. Initialize EGL for Headless environment (Surfaceless context)
    PFNEGLGETPLATFORMDISPLAYEXTPROC eglGetPlatformDisplayEXT = 
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    
    EGLDisplay display = EGL_NO_DISPLAY;
    if (eglGetPlatformDisplayEXT) {
        display = eglGetPlatformDisplayEXT(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, NULL);
    }
    if (display == EGL_NO_DISPLAY) {
        display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    }
    if (display == EGL_NO_DISPLAY) {
        printf("Failed to get EGL display. Are you in the render/video group?\n"); return 1;
    }

    if(!eglInitialize(display, NULL, NULL)) {
        printf("Failed to initialize EGL.\n"); return 1;
    }
    eglBindAPI(EGL_OPENGL_ES_API);

    EGLConfig config;
    EGLint num_config;
    const EGLint attribs[] = { 
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, 
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, 
        EGL_NONE 
    };
    if (!eglChooseConfig(display, attribs, &config, 1, &num_config) || num_config == 0) {
        printf("Failed to find a suitable EGL config.\n"); return 1;
    }

    const EGLint context_attribs[] = { 
        EGL_CONTEXT_CLIENT_VERSION, 3, 
        EGL_NONE 
    };
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attribs);
    if (context == EGL_NO_CONTEXT) {
        printf("Failed to create EGL context.\n"); return 1;
    }
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context);

    printf("[GPU Task] GL_VERSION: %s\n", glGetString(GL_VERSION));

    // 2. Compile Compute Shader
    GLuint shader = glCreateShader(GL_COMPUTE_SHADER);
    if (shader == 0) {
        printf("Failed to create compute shader (is GLES 3.1 supported?).\n");
        return 1;
    }
    glShaderSource(shader, 1, &compute_shader_src, NULL);
    glCompileShader(shader);
    
    GLint compiled = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &compiled);
    if (!compiled) {
        char log[512];
        glGetShaderInfoLog(shader, 512, NULL, log);
        printf("Shader compile failed: %s\n", log);
        return 1;
    }

    GLuint program = glCreateProgram();
    glAttachShader(program, shader);
    glLinkProgram(program);
    
    GLint linked = 0;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    if (!linked) {
        char log[512];
        glGetProgramInfoLog(program, 512, NULL, log);
        printf("Shader link failed: %s\n", log);
        return 1;
    }
    glUseProgram(program);

    // 3. Setup Memory Buffers
    GLuint ssbo[2];
    glGenBuffers(2, ssbo);
    
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[0]);
    glBufferData(GL_SHADER_STORAGE_BUFFER, NUM_ELEMENTS * sizeof(float), NULL, GL_DYNAMIC_DRAW);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, ssbo[0]);

    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
    glBufferData(GL_SHADER_STORAGE_BUFFER, NUM_ELEMENTS * sizeof(float), NULL, GL_DYNAMIC_DRAW);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, ssbo[1]);

    GLenum buf_err = glGetError();
    if (buf_err != GL_NO_ERROR) {
        printf("OpenGL Error allocating buffers: 0x%x\n", buf_err);
        return 1;
    }

    printf("[GPU Task] Allocated %lu MB on GPU.\n", (NUM_ELEMENTS * sizeof(float) * 2) / (1024 * 1024));

    // Calculate workgroups: each thread does 4 elements, workgroup size is 256.
    GLuint workgroups = NUM_ELEMENTS / (256 * 4);

    // Warmup
    glDispatchCompute(workgroups, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    glFinish();

    GLenum err = glGetError();
    if (err != GL_NO_ERROR) {
        printf("OpenGL Error during warmup dispatch: 0x%x\n", err);
        return 1;
    }

    printf("[GPU Task] Running %d iterations of compute shader...\n", ITERATIONS);
    double start_time = get_time();

    for(int i = 0; i < ITERATIONS; i++) {
        glDispatchCompute(workgroups, 1, 1);
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    }
    glFinish(); // Block until GPU operations complete

    double end_time = get_time();
    double duration = end_time - start_time;

    // PREVENT DRIVER OPTIMIZATION: 
    // If the driver sees that we never read the results, it might optimize away the entire dispatch pipeline!
    // We force the driver to execute by mapping the buffer to the CPU and reading a value.
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
    float* out_ptr = (float*)glMapBufferRange(GL_SHADER_STORAGE_BUFFER, 0, sizeof(float), GL_MAP_READ_BIT);
    if (out_ptr) {
        printf("[GPU Task] Verification sample: output[0] = %f\n", out_ptr[0]);
        glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
    } else {
        GLenum map_err = glGetError();
        printf("[GPU Task] Warning: Failed to map buffer for verification. OpenGL Error: 0x%x\n", map_err);
    }

    printf("[GPU Task] Finished. Total GPU time: %.6f seconds.\n", duration);
    return 0;
}

