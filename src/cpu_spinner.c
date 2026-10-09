#include <stdio.h>
#include <stdlib.h>
#include <time.h>

int main(int argc, char *argv[]) {
    int duration = 10;
    if (argc > 1) {
        duration = atoi(argv[1]);
    }

    time_t start_time = time(NULL);
    volatile long long counter = 0;

    // Constantly perform CPU math to max out the CPU core at 100%.
    // Because this uses no arrays or heap memory, it fits entirely inside 
    // the CPU's registers and L1 cache, generating ZERO traffic to the DRAM.
    // This allows us to trigger the SoC's power/clock boost without interfering with memory.
    while (time(NULL) - start_time < duration) {
        for(int i = 0; i < 1000000; i++) {
            counter++;
        }
    }

    return 0;
}

