
#define _POSIX_C_SOURCE 200809L

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl31.h>
#include <GLES2/gl2ext.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include <string.h>
#include <math.h>

#ifndef EGL_PLATFORM_SURFACELESS_MESA
#define EGL_PLATFORM_SURFACELESS_MESA 0x31DD
#endif

#define NUM_ELEMENTS (1024u * 1024u * 8u)
#define ITERATIONS 400

static uint64_t get_time_ns(void)
{
    struct timespec ts;

    if (clock_gettime(CLOCK_MONOTONIC_RAW, &ts) != 0) {
        perror("clock_gettime");
        exit(EXIT_FAILURE);
    }

    return (uint64_t)ts.tv_sec * 1000000000ULL
         + (uint64_t)ts.tv_nsec;
}

static const char *compute_shader_src =
"#version 310 es\n"
"layout(local_size_x = 256) in;\n"
"layout(std430, binding = 0) buffer DataIn { float in_data[]; };\n"
"layout(std430, binding = 1) buffer DataOut { float out_data[]; };\n"
"void main() {\n"
"    uint base = gl_GlobalInvocationID.x * 4u;\n"
"    out_data[base]       = in_data[base]       * 1.0001;\n"
"    out_data[base + 1u]  = in_data[base + 1u]  * 1.0001;\n"
"    out_data[base + 2u]  = in_data[base + 2u]  * 1.0001;\n"
"    out_data[base + 3u]  = in_data[base + 3u]  * 1.0001;\n"
"}\n";

static void print_shader_log(GLuint shader)
{
    char log[2048];
    GLsizei length = 0;

    glGetShaderInfoLog(shader, sizeof(log), &length, log);
    fprintf(stderr, "Shader compilation failed:\n%.*s\n",
            (int)length, log);
}

static void print_program_log(GLuint program)
{
    char log[2048];
    GLsizei length = 0;

    glGetProgramInfoLog(program, sizeof(log), &length, log);
    fprintf(stderr, "Program linking failed:\n%.*s\n",
            (int)length, log);
}

int main(void)
{
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLConfig config;
    EGLint num_configs = 0;
    EGLSurface surface = EGL_NO_SURFACE;

    GLuint shader = 0;
    GLuint program = 0;
    GLuint ssbo[2] = {0, 0};
    GLuint query = 0;

    float *input = NULL;
    float *output = NULL;

    int exit_code = EXIT_FAILURE;

    /* Create a headless OpenGL ES context. */
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_platform_display =
        (PFNEGLGETPLATFORMDISPLAYEXTPROC)
        eglGetProcAddress("eglGetPlatformDisplayEXT");

    if (get_platform_display) {
        display = get_platform_display(
            EGL_PLATFORM_SURFACELESS_MESA,
            EGL_DEFAULT_DISPLAY,
            NULL);
    }

    if (display == EGL_NO_DISPLAY)
        display = eglGetDisplay(EGL_DEFAULT_DISPLAY);

    if (display == EGL_NO_DISPLAY ||
        !eglInitialize(display, NULL, NULL)) {
        fprintf(stderr, "EGL initialization failed\n");
        goto cleanup;
    }

    if (!eglBindAPI(EGL_OPENGL_ES_API)) {
        fprintf(stderr, "eglBindAPI failed\n");
        goto cleanup;
    }

    const EGLint config_attrs[] = {
        EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_NONE
    };

    if (!eglChooseConfig(display, config_attrs, &config,
                         1, &num_configs) ||
        num_configs == 0) {
        fprintf(stderr, "No suitable EGL config\n");
        goto cleanup;
    }

    const EGLint context_attrs[] = {
        EGL_CONTEXT_CLIENT_VERSION, 3,
        EGL_NONE
    };

    context = eglCreateContext(
        display, config, EGL_NO_CONTEXT, context_attrs);

    if (context == EGL_NO_CONTEXT) {
        fprintf(stderr, "EGL context creation failed\n");
        goto cleanup;
    }

    /*
     * A surfaceless context is supported by Mesa.
     * No EGL surface is needed.
     */
    if (!eglMakeCurrent(display, EGL_NO_SURFACE,
                        EGL_NO_SURFACE, context)) {
        fprintf(stderr, "eglMakeCurrent failed\n");
        goto cleanup;
    }

    printf("GL_VERSION: %s\n", glGetString(GL_VERSION));
    printf("GL_RENDERER: %s\n", glGetString(GL_RENDERER));

    /* Compile the compute shader. */
    shader = glCreateShader(GL_COMPUTE_SHADER);
    glShaderSource(shader, 1, &compute_shader_src, NULL);
    glCompileShader(shader);

    GLint compiled = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &compiled);

    if (!compiled) {
        print_shader_log(shader);
        goto cleanup;
    }

    program = glCreateProgram();
    glAttachShader(program, shader);
    glLinkProgram(program);

    GLint linked = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &linked);

    if (!linked) {
        print_program_log(program);
        goto cleanup;
    }

    glUseProgram(program);

    /* Initialize the input with deterministic, nonzero data. */
    const size_t buffer_bytes =
        (size_t)NUM_ELEMENTS * sizeof(float);

    input = malloc(buffer_bytes);

    if (!input) {
        fprintf(stderr, "Input allocation failed\n");
        goto cleanup;
    }

    for (size_t i = 0; i < NUM_ELEMENTS; i++) {
        input[i] = 1.0f + (float)(i % 100) * 0.01f;
    }

    glGenBuffers(2, ssbo);

    /* Input SSBO: initialized data. */
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[0]);
    glBufferData(GL_SHADER_STORAGE_BUFFER,
                 (GLsizeiptr)buffer_bytes,
                 input, GL_DYNAMIC_DRAW);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, ssbo[0]);

    /* Output SSBO: shader overwrites every element. */
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
    glBufferData(GL_SHADER_STORAGE_BUFFER,
                 (GLsizeiptr)buffer_bytes,
                 NULL, GL_DYNAMIC_DRAW);
    glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, ssbo[1]);

    free(input);
    input = NULL;

    GLenum err = glGetError();

    if (err != GL_NO_ERROR) {
        fprintf(stderr, "Buffer allocation error: 0x%x\n", err);
        goto cleanup;
    }

    printf("Allocated %.1f MiB total SSBO storage\n",
           (double)(2ULL * buffer_bytes) / (1024.0 * 1024.0));

    const GLuint workgroups = NUM_ELEMENTS / (256u * 4u);

    GLint max_groups_x = 0;
    glGetIntegeri_v(GL_MAX_COMPUTE_WORK_GROUP_COUNT,
                    0, &max_groups_x);

    if (workgroups > (GLuint)max_groups_x) {
        fprintf(stderr, "Workgroup count exceeds device limit\n");
        goto cleanup;
    }

    printf("Workgroups per dispatch: %u\n", workgroups);

    /* Warm-up run, excluded from measurements. */
    glDispatchCompute(workgroups, 1, 1);
    glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
    glFinish();

    err = glGetError();

    if (err != GL_NO_ERROR) {
        fprintf(stderr, "Warm-up GL error: 0x%x\n", err);
        goto cleanup;
    }

    /*
     * Load GL_EXT_disjoint_timer_query functions.
     */
    PFNGLGENQUERIESEXTPROC gen_queries =
        (PFNGLGENQUERIESEXTPROC)
        eglGetProcAddress("glGenQueriesEXT");

    PFNGLBEGINQUERYEXTPROC begin_query =
        (PFNGLBEGINQUERYEXTPROC)
        eglGetProcAddress("glBeginQueryEXT");

    PFNGLENDQUERYEXTPROC end_query =
        (PFNGLENDQUERYEXTPROC)
        eglGetProcAddress("glEndQueryEXT");

    PFNGLGETQUERYOBJECTUI64VEXTPROC get_query_result =
        (PFNGLGETQUERYOBJECTUI64VEXTPROC)
        eglGetProcAddress("glGetQueryObjectui64vEXT");

    PFNGLGETQUERYOBJECTUIVEXTPROC get_query_available =
        (PFNGLGETQUERYOBJECTUIVEXTPROC)
        eglGetProcAddress("glGetQueryObjectuivEXT");

    const char *extensions =
        (const char *)glGetString(GL_EXTENSIONS);

    int timer_supported =
        extensions &&
        strstr(extensions, "GL_EXT_disjoint_timer_query") &&
        gen_queries && begin_query && end_query &&
        get_query_result && get_query_available;

    if (timer_supported) {
        gen_queries(1, &query);

        if (query == 0)
            timer_supported = 0;
    }

    if (timer_supported) {
        printf("GPU timer query: GL_EXT_disjoint_timer_query available\n");
    } else {
        printf("GPU timer query unavailable; measuring end-to-end only\n");
    }

    /*
     * Measurement:
     * High-resolution per-dispatch or tightly-scoped CPU dispatch latency tracking.
     */
    printf("Running %d dispatches...\n", ITERATIONS);

    struct timespec start_total, end_total;
    clock_gettime(CLOCK_MONOTONIC, &start_total);

    if (timer_supported)
        begin_query(GL_TIME_ELAPSED_EXT, query);

    double total_dispatch_overhead_ns = 0;

    for (int i = 0; i < ITERATIONS; i++) {
        struct timespec dispatch_start, dispatch_end;
        
        // Measure exact CPU submission and driver dispatch overhead per iteration
        clock_gettime(CLOCK_MONOTONIC, &dispatch_start);
        
        glDispatchCompute(workgroups, 1, 1);
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
        
        // Optional: uncomment glFinish() inside the loop if you want strictly synchronous 
        // per-dispatch timing, though it changes async behavior. Keeping it outside 
        // or using fences appropriately measures true queue submission overhead.
        
        clock_gettime(CLOCK_MONOTONIC, &dispatch_end);
        
        double d_ns = (dispatch_end.tv_sec - dispatch_start.tv_sec) * 1e9 + 
                      (dispatch_end.tv_nsec - dispatch_start.tv_nsec);
        total_dispatch_overhead_ns += d_ns;
    }

    if (timer_supported)
        end_query(GL_TIME_ELAPSED_EXT);

    glFinish(); // Ensure all queued GPU commands complete before stopping total timer

    clock_gettime(CLOCK_MONOTONIC, &end_total);

    uint64_t total_e2e_ns = (uint64_t)(end_total.tv_sec - start_total.tv_sec) * 1000000000ULL + 
                            (uint64_t)(end_total.tv_nsec - start_total.tv_nsec);

    const double e2e_ms = total_e2e_ns / 1e6;
    const double avg_dispatch_overhead_us = (total_dispatch_overhead_ns / (double)ITERATIONS) / 1000.0;

    printf("\n========== RESULTS ==========\n");
    printf("Dispatch count:             %d\n", ITERATIONS);
    printf("End-to-end latency:         %.3f ms\n", e2e_ms);
    printf("Avg CPU Dispatch Overhead:  %.3f us/dispatch\n", avg_dispatch_overhead_us);
    if (timer_supported) {
        GLuint available = GL_FALSE;

        while (!available) {
            get_query_available(
                query, GL_QUERY_RESULT_AVAILABLE_EXT, &available);
        }

        GLuint64 gpu_ns = 0;
        get_query_result(query, GL_QUERY_RESULT_EXT, &gpu_ns);

        GLint disjoint = GL_FALSE;
        glGetIntegerv(GL_GPU_DISJOINT_EXT, &disjoint);

        if (disjoint) {
            printf("GPU elapsed time:            INVALID (timer disjoint)\n");
        } else {
            const double gpu_ms = gpu_ns / 1e6;

            printf("GPU elapsed time:            %.3f ms\n", gpu_ms);
            printf("Average GPU time/dispatch:   %.3f us\n",
                   gpu_ns / (double)ITERATIONS / 1000.0);
            printf("E2E minus GPU elapsed:       %.3f ms\n",
                   e2e_ms - gpu_ms);
        }
    }

    /*
     * Read back and validate output outside the timed interval.
     * The expected value accounts for the shader's float operation.
     */
    glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);

    output = glMapBufferRange(
        GL_SHADER_STORAGE_BUFFER,
        0,
        (GLsizeiptr)buffer_bytes,
        GL_MAP_READ_BIT);

    if (!output) {
        fprintf(stderr, "Output mapping failed: 0x%x\n", glGetError());
        goto cleanup;
    }

    size_t errors = 0;
    const size_t check_count = 1024;

    for (size_t i = 0; i < check_count; i++) {
        float expected = input ? input[i] * 1.0001f
                               : (1.0f + (float)(i % 100) * 0.01f)
                                 * 1.0001f;

        if (!isfinite(output[i]) ||
            fabsf(output[i] - expected) > 1e-5f) {
            if (errors < 5) {
                fprintf(stderr,
                        "Mismatch at %zu: actual=%f expected=%f\n",
                        i, output[i], expected);
            }
            errors++;
        }
    }

    printf("Verification output[0]:      %.8f\n", output[0]);
    printf("Elements checked:             %zu\n", check_count);
    printf("Verification errors:          %zu\n", errors);
    printf("Verification:                 %s\n",
           errors == 0 ? "PASS" : "FAIL");

    glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
    output = NULL;

    exit_code = (errors == 0) ? EXIT_SUCCESS : EXIT_FAILURE;

cleanup:
    if (input)
        free(input);

    if (output && ssbo[1]) {
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, ssbo[1]);
        glUnmapBuffer(GL_SHADER_STORAGE_BUFFER);
    }

    if (query)
        glDeleteQueries(1, &query);

    if (ssbo[0] || ssbo[1])
        glDeleteBuffers(2, ssbo);

    if (program)
        glDeleteProgram(program);

    if (shader)
        glDeleteShader(shader);

    if (display != EGL_NO_DISPLAY) {
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                       EGL_NO_CONTEXT);

        if (context != EGL_NO_CONTEXT)
            eglDestroyContext(display, context);

        if (surface != EGL_NO_SURFACE)
            eglDestroySurface(display, surface);

        eglTerminate(display);
    }

    return exit_code;
}
