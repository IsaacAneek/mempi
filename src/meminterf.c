#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

// A 50 MB buffer, matching the HeSoC-mark experiments in the reference material
#define BUFFER_SIZE (50 * 1024 * 1024) 

int main(int argc, char *argv[]) {
    int duration = 10; // default 10 seconds
    if (argc > 1) {
        duration = atoi(argv[1]);
    }

    printf("[Interferer] Starting CPU memory interferer for %d seconds...\n", duration);
    
    char *buffer = (char *)malloc(BUFFER_SIZE);
    if (!buffer) {
        perror("Failed to allocate memory");
        return 1;
    }

    time_t start_time = time(NULL);
    unsigned long long iterations = 0;

    // Constantly write to memory to saturate memory bandwidth.
    // This creates CPU-side memory interference against the shared DRAM.
    while (time(NULL) - start_time < duration) {
        memset(buffer, 0xAA, BUFFER_SIZE);
        iterations++;
    }

    printf("[Interferer] Finished. Completed %llu iterations of 50MB memset.\n", iterations);
    free(buffer);
    return 0;
}

